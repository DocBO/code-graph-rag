from __future__ import annotations

from pathlib import Path

from codebase_rag.language_config import (
    LANGUAGE_CONFIGS,
    LANGUAGE_FQN_CONFIGS,
    PYTHON_FQN_CONFIG,
    TYPESCRIPT_FQN_CONFIG,
    FQNConfig,
    _js_file_to_module,
    _js_get_name,
    _python_file_to_module,
    _python_get_name,
    get_language_config,
    get_language_config_by_name,
)


def _make_id_node(text: str) -> object:
    class NodeStub:
        type = "identifier"

        class Text:
            @staticmethod
            def decode(enc: str) -> str:
                return text

        text = Text()

        def child_by_field_name(self, field: str) -> NodeStub | None:
            if field == "name":
                return self
            return None

    return NodeStub()


def _make_class_def_node(text: str) -> object:
    class NodeStub:
        type = "class_definition"
        name_node = _make_id_node(text)

        def child_by_field_name(self, field: str) -> object | None:
            if field == "name":
                return self.name_node
            return None

    return NodeStub()


def _make_js_func_node(text: str) -> object:
    class Text:
        @staticmethod
        def decode(enc: str) -> str:
            return text

    class NodeStub:
        type = "function_declaration"
        text = Text()

        def child_by_field_name(self, field: str) -> object | None:
            if field == "name":
                return _make_id_node(text)
            return None

    return NodeStub()


class TestPythonFqnConfig:
    def test_python_get_name_extracts_name(self) -> None:
        node = _make_class_def_node("MyClass")
        assert _python_get_name(node) == "MyClass"

    def test_python_get_name_none_when_no_name_field(self) -> None:
        class NodeStub:
            def child_by_field_name(self, field: str) -> None:
                return None

        assert _python_get_name(NodeStub()) is None

    def test_python_file_to_module_strips_py(self) -> None:
        result = _python_file_to_module(Path("/repo/pkg/mod.py"), Path("/repo"))
        assert result == ["pkg", "mod"]

    def test_python_file_to_module_handles_init(self) -> None:
        result = _python_file_to_module(Path("/repo/pkg/__init__.py"), Path("/repo"))
        assert result == ["pkg"]

    def test_python_file_to_module_handles_nested_init(self) -> None:
        result = _python_file_to_module(Path("/repo/a/b/__init__.py"), Path("/repo"))
        assert result == ["a", "b"]

    def test_python_file_to_module_outside_root(self) -> None:
        result = _python_file_to_module(Path("/other/x.py"), Path("/repo"))
        assert result == []

    def test_python_fqn_config_is_registered(self) -> None:
        assert LANGUAGE_FQN_CONFIGS["python"] is PYTHON_FQN_CONFIG
        assert isinstance(PYTHON_FQN_CONFIG, FQNConfig)


class TestTypescriptFqnConfig:
    def test_ts_fqn_config_is_registered(self) -> None:
        assert LANGUAGE_FQN_CONFIGS["typescript"] is TYPESCRIPT_FQN_CONFIG
        assert isinstance(TYPESCRIPT_FQN_CONFIG, FQNConfig)

    def test_ts_has_interface_and_namespace_scopes(self) -> None:
        assert "interface_declaration" in TYPESCRIPT_FQN_CONFIG.scope_node_types
        assert "namespace_definition" in TYPESCRIPT_FQN_CONFIG.scope_node_types

    def test_ts_has_function_signature_type(self) -> None:
        assert "function_signature" in TYPESCRIPT_FQN_CONFIG.function_node_types

    def test_ts_uses_js_name_extraction(self) -> None:
        node = _make_js_func_node("hello")
        assert _js_get_name(node) == "hello"

    def test_js_file_to_module_strips_index(self) -> None:
        result = _js_file_to_module(Path("/repo/src/index.ts"), Path("/repo"))
        assert result == ["src"]

    def test_js_file_to_module_handles_deep_path(self) -> None:
        result = _js_file_to_module(Path("/repo/src/utils/helpers.ts"), Path("/repo"))
        assert result == ["src", "utils", "helpers"]


class TestLanguageConfigs:
    def test_python_config_has_expected_extensions(self) -> None:
        config = LANGUAGE_CONFIGS["python"]
        assert ".py" in config.file_extensions

    def test_typescript_config_has_expected_extensions(self) -> None:
        config = LANGUAGE_CONFIGS["typescript"]
        assert ".ts" in config.file_extensions
        assert ".tsx" in config.file_extensions

    def test_python_config_has_init_package_indicator(self) -> None:
        config = LANGUAGE_CONFIGS["python"]
        assert "__init__.py" in config.package_indicators

    def test_get_language_config_matches_extension(self) -> None:
        assert get_language_config(".py") is LANGUAGE_CONFIGS["python"]
        assert get_language_config(".ts") is LANGUAGE_CONFIGS["typescript"]
        assert get_language_config(".tsx") is LANGUAGE_CONFIGS["typescript"]

    def test_get_language_config_returns_none_for_unknown(self) -> None:
        assert get_language_config(".xyz") is None

    def test_get_language_config_by_name(self) -> None:
        assert get_language_config_by_name("python") is LANGUAGE_CONFIGS["python"]
        assert (
            get_language_config_by_name("TYPESCRIPT") is LANGUAGE_CONFIGS["typescript"]
        )
        assert get_language_config_by_name("unknown") is None
