#!/usr/bin/env python3
"""
Unified startup script for Graph-Code MCP server with real-time watcher.

Launches both the MCP server and real-time updater in a coordinated manner.
The MCP server runs in the foreground, while the real-time updater runs in the background.

Usage:
    uv run python start_mcp_with_watcher.py ~/path/to/repo [OPTIONS]

Examples:
    # Basic startup
    uv run python start_mcp_with_watcher.py ~/my-project

    # With custom Memgraph settings
    uv run python start_mcp_with_watcher.py ~/my-project --host localhost --port 7687

    # With HTTP transport
    uv run python start_mcp_with_watcher.py ~/my-project --transport http --host 127.0.0.1 --port 8765

    # With custom debounce delay
    uv run python start_mcp_with_watcher.py ~/my-project --debounce 30
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Start Graph-Code MCP server with real-time watcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ~/my-project
  %(prog)s ~/my-project --debounce 30
  %(prog)s ~/my-project --transport http --port 8765
        """,
    )

    # Positional argument: repo path
    parser.add_argument(
        "repo_path",
        type=str,
        help="Path to the repository to analyze",
    )

    # Memgraph settings
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Memgraph host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7687,
        help="Memgraph port (default: 7687)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Memgraph batch size override",
    )

    # Real-time updater settings
    parser.add_argument(
        "--debounce",
        type=int,
        default=20,
        help="Debounce delay for real-time updates in seconds (default: 20)",
    )

    # MCP server transport settings
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http"],
        default="stdio",
        help="MCP server transport (default: stdio)",
    )
    parser.add_argument(
        "--mcp-host",
        type=str,
        default="127.0.0.1",
        help="HTTP server host for MCP (default: 127.0.0.1, used with --transport http)",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=8765,
        help="HTTP server port for MCP (default: 8765, used with --transport http)",
    )
    parser.add_argument(
        "--path",
        type=str,
        default="/mcp",
        help="HTTP endpoint path (default: /mcp, used with --transport http)",
    )

    args = parser.parse_args()

    # Resolve the repo path
    repo_path = Path(args.repo_path).expanduser().resolve()
    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    print(f"🚀 Starting Graph-Code MCP Server with Real-Time Watcher")
    print(f"📁 Repository: {repo_path}")
    print(f"🔗 Memgraph: {args.host}:{args.port}")
    print(f"⏱️  Debounce: {args.debounce}s")
    print()

    # Start the real-time updater in the background
    print("Starting real-time updater in background...")
    updater_cmd = [
        sys.executable,
        "-m",
        "codebase_rag.main" if repo_path.parent.name == "code-graph-rag" else "realtime_updater",
    ]

    # Determine the correct command
    try:
        # Try using the main module
        updater_cmd = [
            sys.executable,
            "realtime_updater.py",
            str(repo_path),
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--debounce",
            str(args.debounce),
        ]
    except Exception:
        pass

    try:
        updater_process = subprocess.Popen(
            updater_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"✓ Real-time updater started (PID: {updater_process.pid})")
    except Exception as e:
        print(f"⚠️  Failed to start real-time updater: {e}", file=sys.stderr)
        updater_process = None

    print()

    # Build MCP server command
    mcp_cmd = [
        sys.executable,
        "-m",
        "codebase_rag.main",
        "mcp",
        "--repo-path",
        str(repo_path),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]

    if args.batch_size:
        mcp_cmd.extend(["--batch-size", str(args.batch_size)])

    if args.transport == "http":
        mcp_cmd.extend([
            "--transport",
            "http",
            "--mcp-host",
            args.mcp_host,
            "--mcp-port",
            str(args.mcp_port),
            "--path",
            args.path,
        ])
        print(f"🔌 MCP Server: http://{args.mcp_host}:{args.mcp_port}{args.path}")
    else:
        print("🔌 MCP Server: stdio transport")

    print()
    print("=" * 60)
    print("Graph-Code MCP Server is ready!")
    print("=" * 60)
    print()

    # Start the MCP server in the foreground
    try:
        print("Starting MCP server...")
        mcp_process = subprocess.run(mcp_cmd)
        mcp_exit_code = mcp_process.returncode
    except KeyboardInterrupt:
        print("\n⏹️  Shutting down...")
        mcp_exit_code = 130
    except Exception as e:
        print(f"❌ Failed to start MCP server: {e}", file=sys.stderr)
        mcp_exit_code = 1

    # Cleanup: terminate the updater if it's still running
    if updater_process and updater_process.poll() is None:
        print("Stopping real-time updater...")
        updater_process.terminate()
        try:
            updater_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            updater_process.kill()
        print("✓ Real-time updater stopped")

    sys.exit(mcp_exit_code)


if __name__ == "__main__":
    main()
