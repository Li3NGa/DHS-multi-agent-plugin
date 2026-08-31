"""R7 security regression tests."""

import pytest

from deepseek_multi_agent_plugin.security import TokenAuthenticator


def test_token_cannot_be_shared_between_roles():
    with pytest.raises(ValueError, match="token reused across roles"):
        TokenAuthenticator({"user": "shared-token", "admin": "shared-token"})


def test_same_token_repeated_for_same_role_is_still_deterministic():
    # A mapping cannot contain the same role twice in Python, but rebuilding a
    # mapping with one role must remain valid and preserve the normal lookup.
    auth = TokenAuthenticator({"admin": "admin-token"})
    assert auth.authenticate("Bearer admin-token") == "admin"
