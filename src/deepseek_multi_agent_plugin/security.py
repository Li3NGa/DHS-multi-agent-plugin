"""Token-based RBAC for the HTTP adapter.

Roles are hierarchical: readonly < user < operator < admin. Each endpoint
requires a minimum role, and a bearer token maps to exactly one role.

  readonly -> health / agents / status
  user     -> readonly + run
  operator -> user + run traces, history, session management
  admin    -> operator + agent registration

With no tokens configured the adapter runs open (local/dev mode); the HTTP
surface is the trust boundary, so any network-exposed deployment should
configure tokens. The MCP stdio server is deliberately not gated: it is
launched by a trusted host process and inherits the host's access control.
"""
import hmac
from typing import Dict, Optional

ROLE_LEVELS = {"readonly": 0, "user": 1, "operator": 2, "admin": 3}

REQUIRED_ROLE = {
    "health": "readonly",
    "agents": "readonly",
    "status": "readonly",
    "run": "user",
    "runs.list": "operator",
    "runs.get": "operator",
    "history": "operator",
    "sessions.stats": "operator",
    "sessions.delete": "operator",
    "sessions.cleanup": "operator",
    "register": "admin",
}


class TokenAuthenticator:
    """Maps bearer tokens to roles with timing-safe comparison."""

    def __init__(self, roles: Dict[str, str]):
        """``roles`` maps role name -> token (one token per role)."""
        unknown = set(roles) - set(ROLE_LEVELS)
        if unknown:
            raise ValueError(f"unknown roles: {sorted(unknown)} (known: {sorted(ROLE_LEVELS)})")
        self._by_token = {token: role for role, token in roles.items()}

    def authenticate(self, authorization: str) -> Optional[str]:
        """Role for an ``Authorization: Bearer <token>`` header, else None."""
        if not authorization.startswith("Bearer "):
            return None
        token = authorization[len("Bearer "):].strip()
        for known, role in self._by_token.items():
            if hmac.compare_digest(token, known):
                return role
        return None

    def allows(self, role: str, action: str) -> bool:
        required = REQUIRED_ROLE.get(action)
        if required is None:
            raise ValueError(f"unknown action: {action}")
        return ROLE_LEVELS[role] >= ROLE_LEVELS[required]
