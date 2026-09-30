"""Centralized dependency checking utilities."""

import importlib.util

# Cache dependency checks to avoid repeated module lookups
_dependency_cache: dict[str, bool] = {}


def _check_dependency(module_name: str) -> bool:
    """Check if a module is available, with caching."""
    if module_name not in _dependency_cache:
        _dependency_cache[module_name] = (
            importlib.util.find_spec(module_name) is not None
        )
    return _dependency_cache[module_name]


def has_qdrant_client() -> bool:
    """Check if Qdrant client is available."""
    return _check_dependency("qdrant_client")


def has_remote_qdrant() -> bool:
    """Check if a Qdrant server is configured for the HTTP API path.

    The Python client is not the only way to reach Qdrant: when it is absent but
    a host and port are configured, ``vector_store`` talks to the same server
    over its HTTP API. A configured server therefore satisfies the Qdrant
    requirement even though the ``semantic`` extra is missing.
    """
    from ..config import settings

    return bool(settings.QDRANT_HOST and settings.QDRANT_PORT)


def missing_semantic_dependencies() -> list[str]:
    """List every unmet requirement for semantic search, with its remediation.

    Returns:
        An empty list when semantic search can run. Otherwise one
        operator-facing sentence per missing piece, so a skipped embedding pass
        can name the cause instead of reporting a single catch-all reason.
    """
    from ..config import settings

    missing: list[str] = []
    if not settings.EMBED_ENDPOINT:
        missing.append("EMBED_ENDPOINT is not set")
    if not settings.EMBED_MODEL:
        missing.append("EMBED_MODEL is not set")
    if not has_qdrant_client() and not has_remote_qdrant():
        missing.append(
            "no Qdrant backend: qdrant_client is not importable by this "
            "interpreter and QDRANT_HOST/QDRANT_PORT are not both set "
            "(run `uv sync --extra semantic`, or point QDRANT_HOST and "
            "QDRANT_PORT at a Qdrant server)"
        )
    return missing


def has_semantic_dependencies() -> bool:
    """Check if semantic search dependencies are available.

    Returns:
        True if an external embedder is configured (EMBED_ENDPOINT and
        EMBED_MODEL set) and a Qdrant backend is reachable, either through the
        Python client or through a configured Qdrant server's HTTP API.
    """
    return not missing_semantic_dependencies()


def check_dependencies(required_modules: list[str]) -> bool:
    """Check if all required modules are available.

    Args:
        required_modules: List of module names to check

    Returns:
        True if all modules are available, False otherwise
    """
    return all(_check_dependency(module) for module in required_modules)


def get_missing_dependencies(required_modules: list[str]) -> list[str]:
    """Get list of missing dependencies.

    Args:
        required_modules: List of module names to check

    Returns:
        List of missing module names
    """
    return [module for module in required_modules if not _check_dependency(module)]


# Commonly used dependency combinations
SEMANTIC_DEPENDENCIES = ["qdrant_client"]
