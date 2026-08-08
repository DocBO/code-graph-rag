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
    uv run python start_mcp_with_watcher.py ~/my-project --transport http --mcp-host 127.0.0.1 --mcp-port 8765

    # With custom debounce delay
    uv run python start_mcp_with_watcher.py ~/my-project --debounce 30
"""

import argparse 
import os
import shlex
import socket
import subprocess
import sys
from pathlib import Path


def _run_embedding_only(
    repo_path: Path, host: str, port: int, batch_size: int | None
) -> None:
    """Delete all existing embeddings and regenerate from scratch."""
    from codebase_rag.config import settings
    from codebase_rag.graph_updater import GraphUpdater
    from codebase_rag.parser_loader import load_parsers
    from codebase_rag.services.graph_service import MemgraphIngestor
    from codebase_rag.vector_store import clean_collection

    print("🧹 Cleaning existing embeddings...")
    clean_collection(repo_path)
    print("✓ Embeddings cleaned")

    effective_batch_size = settings.resolve_batch_size(batch_size)

    print("🔌 Connecting to Memgraph...")
    with MemgraphIngestor(
        host=host,
        port=port,
        batch_size=effective_batch_size,
        repo_path=repo_path,
    ) as ingestor:
        parsers, queries = load_parsers()
        updater = GraphUpdater(ingestor, repo_path, parsers, queries)

        print("🔢 Regenerating embeddings from Memgraph data...")
        updater._generate_semantic_embeddings()
        print("✓ Embedding regeneration complete")
        print()


def _can_connect(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if a TCP connection can be established to host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Start Graph-Code MCP server with real-time watcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ~/my-project
  %(prog)s ~/my-project --debounce 30
    %(prog)s ~/my-project --transport http --mcp-port 8765
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
    parser.add_argument(
        "--no-update",
        action="store_true",
        default=False,
        help="Skip the initial full codebase scan; only watch for incremental changes",
    )
    parser.add_argument(
        "--only-embedding",
        action="store_true",
        default=False,
        help="Skip ingestion and watcher; only delete and regenerate embeddings, then start MCP server",
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

    if args.only_embedding:
        print("🎯 Starting Graph-Code MCP Server (embedding-only mode)")
    else:
        print("🚀 Starting Graph-Code MCP Server with Real-Time Watcher")
    print(f"📁 Repository: {repo_path}")
    print(f"🔗 Memgraph: {args.host}:{args.port}")
    if not args.only_embedding:
        print(f"⏱️  Debounce: {args.debounce}s")
    print()

    updater_process = None
    child_env = os.environ.copy()
    child_env["MEMGRAPH_HOST"] = args.host
    child_env["MEMGRAPH_PORT"] = str(args.port)
    print(
        "🧭 Wiring: child process Memgraph endpoint "
        f"MEMGRAPH_HOST={child_env['MEMGRAPH_HOST']} "
        f"MEMGRAPH_PORT={child_env['MEMGRAPH_PORT']}"
    )

    # Preflight Memgraph connectivity before launching child processes.
    if not _can_connect(args.host, args.port):
        print(f"❌ No Memgraph available at {args.host}:{args.port}.", file=sys.stderr)
        print("Stopping startup: updater and MCP server were not started.", file=sys.stderr)
        sys.exit(1)

    if args.only_embedding:
        _run_embedding_only(repo_path, args.host, args.port, args.batch_size)
    else:
        # Start the real-time updater in the background
        print("Starting real-time updater in background...")
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
        if args.batch_size:
            updater_cmd.extend(["--batch-size", str(args.batch_size)])
        if args.no_update:
            updater_cmd.append("--no-update")
        print(f"🧭 Updater command: {shlex.join(updater_cmd)}")

        try:
            updater_process = subprocess.Popen(
                updater_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffering
                env=child_env,
            )
            print(f"✓ Real-time updater started (PID: {updater_process.pid})")
            
            # Start a thread to capture and display updater logs
            def _capture_updater_logs():
                """Capture logs from the background updater process."""
                if updater_process.stdout:
                    for line in updater_process.stdout:
                        print(f"  [updater] {line.rstrip()}")
            
            import threading
            log_thread = threading.Thread(target=_capture_updater_logs, daemon=True)
            log_thread.start()
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
    ]

    if args.batch_size:
        mcp_cmd.extend(["--batch-size", str(args.batch_size)])

    if args.transport == "http":
        mcp_cmd.extend([
            "--transport",
            "http",
            "--host",
            args.mcp_host,
            "--port",
            str(args.mcp_port),
            "--path",
            args.path,
        ])
        print(f"🔌 MCP Server: http://{args.mcp_host}:{args.mcp_port}{args.path}")
    else:
        print("🔌 MCP Server: stdio transport")
    print(f"🧭 MCP command: {shlex.join(mcp_cmd)}")

    print()
    print("=" * 60)
    print("Graph-Code MCP Server is ready!")
    print("=" * 60)
    print()

    # Start the MCP server in the foreground
    try:
        print("Starting MCP server...")
        mcp_process = subprocess.run(mcp_cmd, env=child_env)
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
