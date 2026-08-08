from __future__ import annotations

from pathlib import Path

import pytest

from codebase_rag.tools.shell_command import (
    COMMAND_ALLOWLIST,
    ShellCommander,
    _is_dangerous_command,
    _requires_confirmation,
    create_shell_command_tool,
)


class TestIsDangerousCommand:
    def test_rm_rf_is_dangerous(self) -> None:
        assert _is_dangerous_command(["rm", "-rf", "/"]) is True

    def test_rm_without_rf_is_not_dangerous(self) -> None:
        assert _is_dangerous_command(["rm", "file.txt"]) is False

    def test_echo_is_not_dangerous(self) -> None:
        assert _is_dangerous_command(["echo", "hello"]) is False

    def test_git_status_is_not_dangerous(self) -> None:
        assert _is_dangerous_command(["git", "status"]) is False


class TestRequiresConfirmation:
    def test_rm_needs_confirmation(self) -> None:
        needs, reason = _requires_confirmation(["rm", "file.txt"])
        assert needs is True
        assert "rm" in reason

    def test_mkdir_needs_confirmation(self) -> None:
        needs, _ = _requires_confirmation(["mkdir", "newdir"])
        assert needs is True

    def test_uv_needs_confirmation(self) -> None:
        needs, _ = _requires_confirmation(["uv", "add", "somepackage"])
        assert needs is True

    def test_git_push_needs_confirmation(self) -> None:
        needs, _ = _requires_confirmation(["git", "push"])
        assert needs is True

    def test_git_status_no_confirmation(self) -> None:
        needs, _ = _requires_confirmation(["git", "status"])
        assert needs is False

    def test_git_log_no_confirmation(self) -> None:
        needs, _ = _requires_confirmation(["git", "log"])
        assert needs is False

    def test_ls_no_confirmation(self) -> None:
        needs, _ = _requires_confirmation(["ls", "-la"])
        assert needs is False

    def test_empty_command_no_confirmation(self) -> None:
        needs, _ = _requires_confirmation([])
        assert needs is False


class TestCommandAllowlist:
    def test_ls_in_allowlist(self) -> None:
        assert "ls" in COMMAND_ALLOWLIST

    def test_git_in_allowlist(self) -> None:
        assert "git" in COMMAND_ALLOWLIST

    def test_pytest_in_allowlist(self) -> None:
        assert "pytest" in COMMAND_ALLOWLIST

    def test_ruff_in_allowlist(self) -> None:
        assert "ruff" in COMMAND_ALLOWLIST

    def test_grep_not_in_allowlist(self) -> None:
        assert "grep" not in COMMAND_ALLOWLIST


class TestShellCommander:
    @pytest.fixture
    def commander(self, tmp_path: Path) -> ShellCommander:
        return ShellCommander(project_root=str(tmp_path), timeout=5)

    @pytest.mark.asyncio
    async def test_empty_command(self, commander: ShellCommander) -> None:
        result = await commander.execute("")
        assert result.return_code == -1
        assert "Empty command" in result.stderr

    @pytest.mark.asyncio
    async def test_disallowed_command(self, commander: ShellCommander) -> None:
        result = await commander.execute("grep pattern file")
        assert result.return_code == -1
        assert "not in the allowlist" in result.stderr

    @pytest.mark.asyncio
    async def test_dangerous_command_rejected(self, commander: ShellCommander) -> None:
        result = await commander.execute("rm -rf /")
        assert result.return_code == -1
        assert "Rejected dangerous command" in result.stderr

    @pytest.mark.asyncio
    async def test_requires_confirmation_return_code(
        self, commander: ShellCommander
    ) -> None:
        result = await commander.execute("rm somefile.txt")
        assert result.return_code == -2
        assert "Do you approve?" in result.stdout

    @pytest.mark.asyncio
    async def test_confirmed_command_executes(self, commander: ShellCommander) -> None:
        result = await commander.execute("rm somefile.txt", confirmed=True)
        assert result.return_code != -2

    @pytest.mark.asyncio
    async def test_echo_command(self, commander: ShellCommander) -> None:
        result = await commander.execute("echo hello")
        assert result.return_code == 0
        assert result.stdout == "hello"

    @pytest.mark.asyncio
    async def test_pwd_command(self, commander: ShellCommander) -> None:
        result = await commander.execute("pwd")
        assert result.return_code == 0
        assert result.stdout

    @pytest.mark.asyncio
    async def test_ls_command(self, commander: ShellCommander) -> None:
        result = await commander.execute("ls")
        assert result.return_code == 0

    @pytest.mark.asyncio
    async def test_command_timing_logs(self, commander: ShellCommander) -> None:
        result = await commander.execute("echo test_timing")
        assert result.stdout == "test_timing"


class TestCreateShellCommandTool:
    def test_creates_tool_object(self, tmp_path: Path) -> None:
        commander = ShellCommander(str(tmp_path))
        tool = create_shell_command_tool(commander)
        assert tool is not None
        assert tool.name == "execute_shell_command"
