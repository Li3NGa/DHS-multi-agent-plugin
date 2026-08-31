"""R8 remote HTTP bind security regression tests."""

import ipaddress

import pytest

from deepseek_multi_agent_plugin.adapter_server import build_server, validate_bind_security
from deepseek_multi_agent_plugin.adapters.http import is_loopback_bind_host
from deepseek_multi_agent_plugin.coordinator import AgentCoordinator


def test_loopback_hosts_are_safe_without_auth():
    for host in ("127.0.0.1", "127.0.0.42", "::1", "localhost"):
        assert is_loopback_bind_host(host)
        validate_bind_security(host)


def test_non_loopback_hosts_are_not_treated_as_local():
    for host in ("0.0.0.0", "::", "192.0.2.10", "example.internal"):
        assert not is_loopback_bind_host(host)
        with pytest.raises(ValueError, match="refusing unauthenticated remote HTTP bind"):
            validate_bind_security(host)


def test_build_server_rejects_remote_bind_without_authentication():
    with pytest.raises(ValueError, match="refusing unauthenticated remote HTTP bind"):
        build_server("0.0.0.0", 0, AgentCoordinator())


def test_remote_bind_accepts_single_token_or_roles():
    validate_bind_security("0.0.0.0", token="admin-token")
    validate_bind_security("0.0.0.0", roles={"readonly": "ro-token"})
    validate_bind_security("::", token="admin-token")


def test_build_server_allows_authenticated_remote_bind():
    server = build_server("0.0.0.0", 0, AgentCoordinator(), token="admin-token")
    server.server_close()


def test_remote_bind_requires_explicit_insecure_opt_in():
    validate_bind_security("0.0.0.0", allow_insecure_remote=True)


def test_loopback_detection_matches_ipaddress_semantics_for_ipv4_and_ipv6():
    assert is_loopback_bind_host(str(ipaddress.ip_address("127.0.0.2")))
    assert is_loopback_bind_host(str(ipaddress.ip_address("::1")))
