from __future__ import annotations

from codebase_rag.utils.dependencies import (
    _check_dependency,
    _dependency_cache,
    check_dependencies,
    get_missing_dependencies,
    has_qdrant_client,
    has_semantic_dependencies,
)


class TestCheckDependency:
    def test_builtin_module_found(self) -> None:
        assert _check_dependency("os") is True
        assert _check_dependency("sys") is True

    def test_nonexistent_module_not_found(self) -> None:
        assert _check_dependency("nonexistent_module_xyz_123") is False

    def test_cache_is_populated(self) -> None:
        _dependency_cache.clear()
        assert "os" not in _dependency_cache
        _check_dependency("os")
        assert "os" in _dependency_cache
        assert _dependency_cache["os"] is True

    def test_cached_result_returned(self) -> None:
        _dependency_cache.clear()
        _dependency_cache["fake_mod"] = True
        assert _check_dependency("fake_mod") is True


class TestConvenienceFunctions:
    def test_has_qdrant_client_may_be_false(self) -> None:
        result = has_qdrant_client()
        assert isinstance(result, bool)

    def test_has_semantic_dependencies_returns_bool(self) -> None:
        result = has_semantic_dependencies()
        assert isinstance(result, bool)


class TestCheckDependencies:
    def test_all_builtins_pass(self) -> None:
        assert check_dependencies(["os", "sys", "json"]) is True

    def test_missing_module_fails(self) -> None:
        assert check_dependencies(["os", "not_a_real_module_xyz"]) is False

    def test_empty_list_passes(self) -> None:
        assert check_dependencies([]) is True


class TestGetMissingDependencies:
    def test_returns_missing_only(self) -> None:
        missing = get_missing_dependencies(["os", "no_such_mod"])
        assert missing == ["no_such_mod"]

    def test_empty_when_all_present(self) -> None:
        assert get_missing_dependencies(["os", "sys"]) == []

    def test_empty_list_no_missing(self) -> None:
        assert get_missing_dependencies([]) == []
