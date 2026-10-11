import asyncio
import os
import shlex
from pathlib import Path
from typing import cast

from loguru import logger
from pydantic_ai import Tool

from ..schemas import ShellCommandResult

READ_ONLY_GIT_SUBCOMMANDS = frozenset(
    {
        "blame",
        "cat-file",
        "describe",
        "diff",
        "log",
        "ls-files",
        "ls-tree",
        "rev-list",
        "rev-parse",
        "show",
        "show-ref",
        "shortlog",
        "status",
    }
)

# Subcommands that accept --textconv/--ext-diff; forced off for safety.
_TEXTCONV_SUBCOMMANDS = frozenset({"diff", "log", "show"})
_FORCED_FLAGS = ("--no-ext-diff", "--no-textconv")

# Git accepts unambiguous prefixes of long options, so any argument that is a
# prefix of one of these is rejected (e.g. "--out=x" is treated as "--output").
_DENIED_LONG_OPTIONS = (
    "--contents",
    "--exec",
    "--ext-diff",
    "--no-index",
    "--output",
    "--receive-pack",
    "--textconv",
    "--upload-pack",
)

MAX_OUTPUT_CHARS = 20_000


def _error(message: str) -> ShellCommandResult:
    return ShellCommandResult(return_code=-1, stdout="", stderr=message)


def _is_denied_option(arg: str) -> bool:
    if not arg.startswith("--") or arg == "--":
        return False
    name = arg.split("=", 1)[0]
    return any(denied.startswith(name) for denied in _DENIED_LONG_OPTIONS)


class GitReader:
    """Runs an allowlisted set of read-only git subcommands in the project root."""

    def __init__(self, project_root: str = ".", timeout: int = 30):
        self.project_root = Path(project_root).resolve()
        self.timeout = timeout

    async def execute(self, command: str) -> ShellCommandResult:
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return _error(f"Could not parse git command: {e}")

        if parts[:1] == ["git"]:
            parts = parts[1:]
        if not parts:
            return _error("Empty git command provided.")

        subcommand, args = parts[0], parts[1:]
        if subcommand not in READ_ONLY_GIT_SUBCOMMANDS:
            allowed = ", ".join(sorted(READ_ONLY_GIT_SUBCOMMANDS))
            return _error(
                f"Git subcommand '{subcommand}' is not allowed in read-only mode. "
                f"Allowed: {allowed}"
            )

        for arg in args:
            if _is_denied_option(arg):
                return _error(f"Git option '{arg}' is not allowed in read-only mode.")

        argv = ["git", "--no-pager", subcommand]
        if subcommand in _TEXTCONV_SUBCOMMANDS:
            argv.extend(_FORCED_FLAGS)
        argv.extend(args)

        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"GIT_DIR", "GIT_WORK_TREE"}
        }
        env.update(
            GIT_PAGER="cat",
            GIT_TERMINAL_PROMPT="0",
            GIT_OPTIONAL_LOCKS="0",
        )

        logger.info(f"Running read-only git command: {' '.join(argv)}")
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=self.project_root,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout
            )
        except TimeoutError:
            if process is not None:
                process.kill()
                await process.wait()
            return _error(f"Git command timed out after {self.timeout} seconds.")
        except Exception as e:
            logger.error(f"Git command failed: {e}")
            return _error(str(e))

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        if len(stdout_str) > MAX_OUTPUT_CHARS:
            stdout_str = (
                stdout_str[:MAX_OUTPUT_CHARS]
                + f"\n... [output truncated at {MAX_OUTPUT_CHARS} characters]"
            )
        return ShellCommandResult(
            return_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout_str,
            stderr=stderr.decode("utf-8", errors="replace").strip(),
        )


def create_git_read_tool(git_reader: GitReader) -> Tool:
    """Factory for the read-only git tool used by the read-only agent."""

    async def run_git_readonly(command: str) -> ShellCommandResult:
        return cast(ShellCommandResult, await git_reader.execute(command))

    return Tool(
        function=run_git_readonly,
        name="run_git_readonly",
        description=(
            "Runs a read-only git command in the repository (for history, blame, "
            "diffs, tracked files). Allowed subcommands: "
            f"{', '.join(sorted(READ_ONLY_GIT_SUBCOMMANDS))}. Pass the full command, "
            "e.g. 'git log --oneline -n 20 -- path/to/file.py'. Write operations and "
            "options that write files or run external programs are rejected."
        ),
    )
