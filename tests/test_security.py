"""RBAC 鉴权与日志脱敏测试。"""
import http.client
import json
import threading
import time
from urllib import request as urlreq
from urllib.error import HTTPError

import pytest

from deepseek_multi_agent_plugin.adapter_server import (
    _parse_roles,
    build_server,
    redact,
    register_demo_agents,
)
from deepseek_multi_agent_plugin.coordinator import AgentCoordinator
from deepseek_multi_agent_plugin.security import REQUIRED_ROLE, TokenAuthenticator

ROLES = {"readonly": "ro-token", "user": "user-token",
         "operator": "op-token", "admin": "admin-token"}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _start_roles_server():
    coord = AgentCoordinator()
    register_demo_agents(coord)
    server = build_server("127.0.0.1", 0, coord, roles=ROLES)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _request(server, path, token=None, method=None, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = _bearer(token) if token else {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urlreq.Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urlreq.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode())


def _expect_error(server, path, token, code, method="GET"):
    headers = _bearer(token) if token else {}
    data = None
    if method == "POST":
        data = b"{}"
        headers["Content-Type"] = "application/json"
    req = urlreq.Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urlreq.urlopen(req, timeout=10):
            raise AssertionError(f"expected HTTP {code}")
    except HTTPError as exc:
        assert exc.code == code
        return json.loads(exc.read().decode())


# ---------------------------------------------------------------- 纯逻辑
def test_authenticator_maps_token_to_role():
    auth = TokenAuthenticator(ROLES)
    assert auth.authenticate("Bearer admin-token") == "admin"
    assert auth.authenticate("Bearer ro-token") == "readonly"
    assert auth.authenticate("Bearer nope") is None
    assert auth.authenticate("Basic admin-token") is None
    assert auth.authenticate("") is None


def test_authenticator_rejects_unknown_roles():
    with pytest.raises(ValueError, match="unknown roles"):
        TokenAuthenticator({"superuser": "t"})


def test_authenticator_rejects_empty_tokens():
    # 空 token 会让任意“Bearer ”都通过鉴权——必须从构造层面拒绝。
    with pytest.raises(ValueError, match="empty token"):
        TokenAuthenticator({"admin": ""})
    with pytest.raises(ValueError, match="empty token"):
        TokenAuthenticator({"admin": "   "})


def test_role_hierarchy_allows_and_denies():
    auth = TokenAuthenticator(ROLES)
    assert auth.allows("readonly", "health")
    assert not auth.allows("readonly", "run")
    assert auth.allows("user", "run")
    assert not auth.allows("user", "runs.list")
    assert auth.allows("operator", "runs.list")
    assert not auth.allows("operator", "register")
    assert auth.allows("admin", "register")


def test_every_endpoint_has_a_role():
    assert set(REQUIRED_ROLE) == {
        "health", "agents", "status", "run", "runs.list", "runs.get",
        "history", "sessions.stats", "sessions.delete", "sessions.cleanup",
        "register",
    }


def test_allows_rejects_unknown_action():
    auth = TokenAuthenticator(ROLES)
    with pytest.raises(ValueError, match="unknown action"):
        auth.allows("admin", "nonsense")


def test_parse_roles_cli_and_env():
    roles = _parse_roles(["admin:tok1", "user:tok2"], None)
    assert roles == {"admin": "tok1", "user": "tok2"}
    merged = _parse_roles(["operator:tok3"], '{"admin": "tok1"}')
    assert merged == {"admin": "tok1", "operator": "tok3"}
    with pytest.raises(SystemExit):
        _parse_roles(["bad"], None)
    with pytest.raises(SystemExit):
        _parse_roles(None, '["not", "an", "object"]')
    # 环境变量 JSON 中的空 token 必须被拒绝（否则等于无鉴权）。
    with pytest.raises(SystemExit):
        _parse_roles(None, '{"admin": ""}')


def test_redact_masks_tokens():
    assert redact("Authorization: Bearer sk-abc123") == "Authorization: Bearer ***"
    assert redact("key=sk-abc123 ghp-xyz pypi-qq") == "key=*** *** ***"
    assert redact("no secrets here") == "no secrets here"


# ---------------------------------------------------------------- 端点矩阵
def test_readonly_role_can_read_but_not_run():
    server = _start_roles_server()
    try:
        assert _request(server, "/health", "ro-token")[1]["status"] == "ok"
        _expect_error(server, "/run", "ro-token", 403, method="POST")
    finally:
        server.shutdown()
        server.server_close()


def test_user_role_can_run_but_not_read_traces_or_register():
    server = _start_roles_server()
    try:
        status, body = _request(
            server, "/run", "user-token",
            payload={"type": "run", "prompt": "hi", "strategy": "broadcast", "rounds": 1},
        )
        assert status == 200
        _expect_error(server, "/runs", "user-token", 403)
        _expect_error(server, "/register", "user-token", 403, method="POST")
    finally:
        server.shutdown()
        server.server_close()


def test_operator_role_manages_sessions_but_cannot_register():
    server = _start_roles_server()
    try:
        status, body = _request(server, "/sessions/cleanup", "op-token", method="POST",
                                payload={"type": "cleanup"})
        assert status == 200
        assert body == {"evicted": []}
        _expect_error(server, "/register", "op-token", 403, method="POST")
    finally:
        server.shutdown()
        server.server_close()


def test_admin_role_can_register_agents():
    server = _start_roles_server()
    try:
        status, body = _request(
            server, "/register", "admin-token",
            payload={"type": "register", "agents": [{"name": "gamma", "kind": "echo"}]},
        )
        assert status == 200
        assert body == {"registered": ["gamma"]}
    finally:
        server.shutdown()
        server.server_close()


def test_forbidden_response_names_required_role():
    server = _start_roles_server()
    try:
        body = _expect_error(server, "/register", "user-token", 403, method="POST")
        assert body == {"error": "forbidden", "required_role": "admin"}
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_path_still_requires_a_token():
    server = _start_roles_server()
    try:
        body = _expect_error(server, "/nope", "ro-token", 404)
        assert body == {"error": "not found"}
        # 未认证时 401 优先于 404
        _expect_error(server, "/nope", None, 401)
    finally:
        server.shutdown()
        server.server_close()


def test_role_token_cannot_impersonate_higher_role_endpoints():
    server = _start_roles_server()
    try:
        # user 令牌可以读 agents（readonly 范围），但读不到 runs
        assert _request(server, "/agents", "user-token")[0] == 200
        _expect_error(server, "/runs", "user-token", 403)
        _expect_error(server, "/runs/missing", "user-token", 403)
        _expect_error(server, "/history", "user-token", 403)
        _expect_error(server, "/sessions", "user-token", 403)
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------- HTTP 加固
def test_http_rejects_negative_content_length():
    server = _start_roles_server()
    try:
        # Content-Length: -1 若被接受，read(-1) 会一直读到连接关闭（DoS）。
        req = urlreq.Request(
            f"http://127.0.0.1:{server.server_port}/run",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "-1",
                ** _bearer("admin-token"),
            },
            method="POST",
        )
        try:
            with urlreq.urlopen(req, timeout=10):
                raise AssertionError("expected HTTP 400")
        except HTTPError as exc:
            assert exc.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_http_rejects_ambiguous_content_length():
    server = _start_roles_server()
    try:
        # 两个冲突的 Content-Length 头是请求走私特征，必须拒绝。
        # Windows 上服务器关闭连接与客户端读取之间存在 socket 半关闭竞态，
        # 因此对瞬时 ConnectionError 做有限重试。
        for attempt in range(3):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            try:
                conn.putrequest("POST", "/run")
                conn.putheader("Content-Type", "application/json")
                conn.putheader("Content-Length", "2")
                conn.putheader("Content-Length", "999")
                conn.putheader("Authorization", "Bearer admin-token")
                conn.endheaders()
                conn.send(b"{}")
                resp = conn.getresponse()
                status = resp.status
                resp.read()
                conn.close()
                assert status == 400
                return
            except ConnectionError:
                conn.close()
                if attempt == 2:
                    raise
                time.sleep(0.2)
    finally:
        server.shutdown()
        server.server_close()


def test_http_rejects_non_json_content_type():
    server = _start_roles_server()
    try:
        # text/plain 是跨站 simple request，可绕过 CORS preflight——必须拒绝，
        # 否则本地恶意网页可触发无鉴权服务执行 run。
        req = urlreq.Request(
            f"http://127.0.0.1:{server.server_port}/run",
            data=b'{"type": "run", "prompt": "hi"}',
            headers={"Content-Type": "text/plain", **_bearer("admin-token")},
            method="POST",
        )
        try:
            with urlreq.urlopen(req, timeout=10):
                raise AssertionError("expected HTTP 415")
        except HTTPError as exc:
            assert exc.code == 415
    finally:
        server.shutdown()
        server.server_close()


def test_server_header_omits_python_version():
    server = _start_roles_server()
    try:
        with urlreq.urlopen(
            urlreq.Request(
                f"http://127.0.0.1:{server.server_port}/health",
                headers=_bearer("ro-token"),
            ),
            timeout=10,
        ) as resp:
            server_header = resp.headers.get("Server", "")
        assert "Python" not in server_header
        assert server_header.startswith("DHS-Multi-Agent")
    finally:
        server.shutdown()
        server.server_close()
