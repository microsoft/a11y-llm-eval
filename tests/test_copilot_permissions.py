"""Tests for the scoped permission handler (Phase 2 fix)."""

import pytest
from unittest.mock import MagicMock
from a11y_llm_tests.copilot_runtime import _make_scoped_permission_handler


class FakePermissionRequestKind:
    """Mimics PermissionRequestKind enum."""

    def __init__(self, value: str):
        self.value = value


class FakePermissionRequest:
    """Mimics the SDK's PermissionRequest object."""

    def __init__(self, kind: str, path: str = None, file_name: str = None,
                 tool_name: str = None):
        self.kind = FakePermissionRequestKind(kind)
        self.path = path
        self.file_name = file_name
        self.tool_name = tool_name


def _call_handler(handler, request, invocation=None):
    """Call a permission handler with the correct SDK signature."""
    if invocation is None:
        invocation = {}
    return handler(request, invocation)


class TestScopedPermissionHandler:
    def test_no_workdir_returns_approve_all(self):
        handler = _make_scoped_permission_handler(None)
        # When no workdir, we get PermissionHandler.approve_all
        assert handler.__name__ == "approve_all"

    def test_write_inside_workdir_approved(self):
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("write", path="/workspace/sandbox/control/test/model__s0/index.html")
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

    def test_write_outside_workdir_denied(self):
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("write", path="/workspace/config/models.yaml")
        result = _call_handler(handler, req)
        assert result.kind == "reject"

    def test_write_relative_path_inside_workdir_approved(self):
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("write", path="index.html")
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

    def test_write_relative_path_with_traversal_denied(self):
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("write", path="/workspace/a11y_llm_tests/cli.py")
        result = _call_handler(handler, req)
        assert result.kind == "reject"

    def test_read_request_always_approved(self):
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("read", path="/workspace/config/models.yaml")
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

    def test_shell_request_always_approved(self):
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("shell")
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

    def test_mcp_request_always_approved(self):
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("mcp")
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

    def test_write_to_workdir_root_approved(self):
        """Writing to the workdir itself (not a subpath) should be allowed."""
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("write", path="/workspace/sandbox/control/test/model__s0")
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

    def test_empty_path_write_approved(self):
        """When the path can't be determined, allow to avoid blocking legitimate writes."""
        handler = _make_scoped_permission_handler("/workspace/sandbox/x")
        req = FakePermissionRequest("write")
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

    def test_write_uses_file_name_fallback(self):
        """Falls back to file_name when path is None."""
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest("write", file_name="/workspace/sandbox/control/test/model__s0/index.html")
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

    def test_write_to_session_state_approved(self):
        """SDK internal session-state writes (plan.md) should be allowed."""
        handler = _make_scoped_permission_handler("/workspace/sandbox/control/test/model__s0")
        req = FakePermissionRequest(
            "write",
            path="/copilot/.copilot/session-state/7b2cd492-23f6-440b-a058-1fbe513a049c/plan.md",
        )
        result = _call_handler(handler, req)
        assert result.kind == "approve-once"

