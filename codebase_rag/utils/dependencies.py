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


def has_semantic_dependencies() -> bool:
    """Check if semantic search dependencies are available.

    Returns:
        True if an external embedder is configured (EMBED_ENDPOINT and
        EMBED_MODEL set) and the Qdrant client is available.
    """
    from ..config import settings

    if not (settings.EMBED_ENDPOINT and settings.EMBED_MODEL):
        return False
    return has_qdrant_client()


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
