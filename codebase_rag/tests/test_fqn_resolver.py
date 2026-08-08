from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tsp
import tree_sitter_typescript as tst
from tree_sitter import Language, Parser

from codebase_rag.language_config import (
    PYTHON_FQN_CONFIG,
    TYPESCRIPT_FQN_CONFIG,
)
from codebase_rag.utils.fqn_resolver import (
    extract_function_fqns,
    find_function_source_by_fqn,
    resolve_fqn_from_ast,
)

PY_LANG = Language(tsp.language())
PY_PARSER = Parser(PY_LANG)

TS_LANG = Language(tst.language_typescript())
TS_PARSER = Parser(TS_LANG)


class TestResolveFqnPython:
    def test_top_level_function(self) -> None:
        code = b"def hello():\n    pass\n"
        tree = PY_PARSER.parse(code)
        func_node = tree.root_node.children[0]
        fqn = resolve_fqn_from_ast(
            func_node,
            Path("/repo/pkg/mod.py"),
            Path("/repo"),
            "myproject",
            PYTHON_FQN_CONFIG,
        )
        assert fqn == "myproject.pkg.mod.hello"

    def test_function_inside_class(self) -> None:
        code = b"class MyClass:\n    def method(self):\n        pass\n"
        tree = PY_PARSER.parse(code)
        class_node = tree.root_node.children[0]
        block_node = class_node.children[3]
        func_node = block_node.children[0]
        fqn = resolve_fqn_from_ast(
            func_node,
            Path("/repo/pkg/mod.py"),
            Path("/repo"),
            "myproject",
            PYTHON_FQN_CONFIG,
        )
        assert fqn == "myproject.pkg.mod.MyClass.method"

    def test_nested_class(self) -> None:
        code = (
            b"class Outer:\n"
            b"    class Inner:\n"
            b"        def deep(self):\n"
            b"            pass\n"
        )
        tree = PY_PARSER.parse(code)
        fqn = None
        for fn in extract_function_fqns(
            tree.root_node,
            Path("/repo/pkg/mod.py"),
            Path("/repo"),
            "myproject",
            PYTHON_FQN_CONFIG,
        ):
            fqn = fn[0]
        assert fqn == "myproject.pkg.mod.Outer.Inner.deep"


class TestResolveFqnTypescript:
    def test_top_level_function(self) -> None:
        code = b"function greet(name: string): void { console.log(name); }"
        tree = TS_PARSER.parse(code)
        func_node = tree.root_node.children[0]
        fqn = resolve_fqn_from_ast(
            func_node,
            Path("/repo/src/utils.ts"),
            Path("/repo"),
            "myproject",
            TYPESCRIPT_FQN_CONFIG,
        )
        assert fqn == "myproject.src.utils.greet"

    def test_method_in_class(self) -> None:
        code = (
            b"class Calculator {\n"
            b"    add(a: number, b: number): number { return a + b; }\n"
            b"}\n"
        )
        tree = TS_PARSER.parse(code)
        fqn = None
        for fn in extract_function_fqns(
            tree.root_node,
            Path("/repo/src/calc.ts"),
            Path("/repo"),
            "myproject",
            TYPESCRIPT_FQN_CONFIG,
        ):
            fqn = fn[0]
        assert fqn == "myproject.src.calc.Calculator.add"

    def test_function_in_namespace(self) -> None:
        code = (
            b"namespace Utils {\n"
            b"    export function format(s: string): string { return s.trim(); }\n"
            b"}\n"
        )
        tree = TS_PARSER.parse(code)
        fqn = None
        for fn in extract_function_fqns(
            tree.root_node,
            Path("/repo/src/helpers.ts"),
            Path("/repo"),
            "myproject",
            TYPESCRIPT_FQN_CONFIG,
        ):
            fqn = fn[0]
        assert fqn == "myproject.src.helpers.format"


class TestFindFunctionSourceByFqn:
    def test_finds_python_function(self) -> None:
        code = b"def hello():\n    return 42\n"
        tree = PY_PARSER.parse(code)
        result = find_function_source_by_fqn(
            tree.root_node,
            "myproject.pkg.mod.hello",
            Path("/repo/pkg/mod.py"),
            Path("/repo"),
            "myproject",
            PYTHON_FQN_CONFIG,
        )
        assert result == "def hello():\n    return 42"

    def test_returns_none_when_not_found(self) -> None:
        code = b"def hello():\n    pass\n"
        tree = PY_PARSER.parse(code)
        result = find_function_source_by_fqn(
            tree.root_node,
            "myproject.pkg.mod.nonexistent",
            Path("/repo/pkg/mod.py"),
            Path("/repo"),
            "myproject",
            PYTHON_FQN_CONFIG,
        )
        assert result is None


class TestExtractFunctionFqns:
    def test_extracts_multiple_functions(self) -> None:
        code = b"def a():\n    pass\ndef b():\n    pass\n"
        tree = PY_PARSER.parse(code)
        fqns = extract_function_fqns(
            tree.root_node,
            Path("/repo/pkg/mod.py"),
            Path("/repo"),
            "myproject",
            PYTHON_FQN_CONFIG,
        )
        assert len(fqns) == 2
        names = [f[0] for f in fqns]
        assert "myproject.pkg.mod.a" in names
        assert "myproject.pkg.mod.b" in names

    def test_extracts_class_methods(self) -> None:
        code = (
            b"class Foo:\n"
            b"    def bar(self):\n"
            b"        pass\n"
            b"    def baz(self):\n"
            b"        pass\n"
        )
        tree = PY_PARSER.parse(code)
        fqns = extract_function_fqns(
            tree.root_node,
            Path("/repo/pkg/mod.py"),
            Path("/repo"),
            "myproject",
            PYTHON_FQN_CONFIG,
        )
        assert len(fqns) == 2
        names = [f[0] for f in fqns]
        assert "myproject.pkg.mod.Foo.bar" in names
        assert "myproject.pkg.mod.Foo.baz" in names
