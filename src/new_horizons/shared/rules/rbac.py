"""RBAC enforcement over shared/rules/rules.yaml.

check(role, tool) -> "allowed" | "approval_required" | raises AccessDenied.
JWT helpers for the A2A bearer scheme (HS256, a `role` field in the token).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_RULES_PATH = Path(__file__).parent / "rules.yaml"
_rules = None


class AccessDenied(PermissionError):
    def __init__(self, role: str, tool: str, reason: str):
        super().__init__(f"rules: role '{role}' denied tool '{tool}' ({reason})")
        self.role, self.tool, self.reason = role, tool, reason


def rules() -> dict:
    global _rules
    if _rules is None:
        _rules = yaml.safe_load(_RULES_PATH.read_text())
    return _rules


def check(role: str, tool: str) -> str:
    tools = rules()["tools"]
    if tool not in tools:
        raise AccessDenied(role, tool, "unknown tool")
    spec = tools[tool]
    if role not in spec["roles"]:
        raise AccessDenied(role, tool, f"allowed roles: {spec['roles']}")
    return "approval_required" if spec.get("approval_required") else "allowed"


# ---- JWT (A2A bearer) -------------------------------------------------------

def _secret() -> str:
    return os.environ["A2A_JWT_SECRET"]


def issue_token(role: str, sub: str) -> str:
    import jwt
    return jwt.encode({"role": role, "sub": sub}, _secret(), algorithm="HS256")


def validate_token(token: str) -> dict:
    """The token's payload; raises jwt exceptions / KeyError on invalid tokens."""
    import jwt
    payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    if "role" not in payload:
        raise jwt.InvalidTokenError("missing role field")
    return payload
