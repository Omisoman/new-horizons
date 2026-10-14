"""RBAC rule semantics — deny is an error, approval is a distinct state."""

import pytest

from new_horizons.shared.rules.rbac import AccessDenied, check


def test_ops_allowed_plain_tools():
    assert check("ops", "gitea_pr") == "allowed"
    assert check("ops", "build_run") == "allowed"
    assert check("ops", "validate_smoke") == "allowed"


def test_deploy_requires_approval_for_every_allowed_role():
    assert check("ops", "deploy_staging") == "approval_required"
    assert check("admin", "deploy_staging") == "approval_required"


def test_tier1_denied_ops_tools():
    with pytest.raises(AccessDenied):
        check("tier1-dev", "deploy_staging")
    with pytest.raises(AccessDenied):
        check("tier1-dev", "gitea_pr")


def test_tier1_allowed_delegation_only():
    assert check("tier1-dev", "a2a_delegate") == "allowed"


def test_unknown_tool_is_denied_not_skipped():
    with pytest.raises(AccessDenied):
        check("admin", "rm_rf_everything")


def test_unknown_role_is_denied():
    with pytest.raises(AccessDenied):
        check("intern", "build_run")
