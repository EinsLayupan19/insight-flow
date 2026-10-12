"""The backend must also run on Python 3.12, the oldest supported version (Ubuntu 24.04's Python).

Development uses a newer Python, so these checks look for the two ways code can work there and break on 3.12:
- syntax newer than 3.12 (checked with Python 3.12's grammar);
- annotations that name something defined later in the file. Python 3.14 evaluates annotations only when asked,
  so that works there; Python 3.12 evaluates them when the function or class is defined, and the import fails.

They cannot see a standard-library function added after 3.12. The full test suite on Python 3.12 covers that:
see "Python versions" in the README (.github/workflows/backend.yml runs it).
"""

import ast
import builtins
from pathlib import Path

import pytest

MINIMUM_PYTHON = (3, 12)
BACKEND = Path(__file__).resolve().parent.parent
SOURCES = sorted([*BACKEND.glob("app/**/*.py"), *BACKEND.glob("tests/**/*.py")])


def source_id(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()


@pytest.mark.parametrize("path", SOURCES, ids=source_id)
def test_uses_python_3_12_syntax(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=MINIMUM_PYTHON)


@pytest.mark.parametrize("path", SOURCES, ids=source_id)
def test_annotations_only_name_what_is_already_defined(path: Path) -> None:
    assert late_annotation_names(path.read_text(encoding="utf-8")) == []


def test_the_checks_catch_newer_syntax_and_late_names() -> None:
    """The checks themselves: code that runs on 3.14 but not on 3.12 is reported."""
    with pytest.raises(SyntaxError):
        ast.parse("try:\n    pass\nexcept ValueError, TypeError:\n    pass\n", feature_version=MINIMUM_PYTHON)
    late = "def first() -> Later:\n    pass\n\nclass Later:\n    pass\n"
    assert late_annotation_names(late) == ["Later (line 1)"]
    quoted = "def first() -> 'Later':\n    pass\n\nclass Later:\n    pass\n"
    assert late_annotation_names(quoted) == []


def late_annotation_names(source: str) -> list[str]:
    """Names used in eagerly evaluated annotations before the module defines them."""
    tree = ast.parse(source)
    if any(isinstance(node, ast.ImportFrom) and node.module == "__future__" for node in tree.body):
        return []  # `from __future__ import annotations` keeps every annotation unevaluated on 3.12 too
    defined = set(dir(builtins))
    late: list[str] = []
    for statement in tree.body:
        late += _undefined(_annotations_of(statement), defined)
        defined |= _names_bound_by(statement)
    return late


def _annotations_of(statement: ast.stmt) -> list[ast.expr]:
    """Annotations Python 3.12 evaluates when this module-level statement runs."""
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _signature_annotations(statement)
    if isinstance(statement, ast.AnnAssign):
        return [statement.annotation]
    if isinstance(statement, ast.ClassDef):
        found: list[ast.expr] = []
        for member in statement.body:  # class bodies run at definition time, including method signatures
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found += _signature_annotations(member)
            elif isinstance(member, ast.AnnAssign):
                found.append(member.annotation)
        return found
    return []


def _signature_annotations(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    arguments = function.args
    every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]
    found = [argument.annotation for argument in every if argument is not None and argument.annotation is not None]
    return found + ([function.returns] if function.returns is not None else [])


def _undefined(annotations: list[ast.expr], defined: set[str]) -> list[str]:
    return [
        f"{node.id} (line {node.lineno})"
        for annotation in annotations
        for node in ast.walk(annotation)
        if isinstance(node, ast.Name) and node.id not in defined
    ]


def _names_bound_by(statement: ast.stmt) -> set[str]:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {statement.name}
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return {(alias.asname or alias.name).split(".")[0] for alias in statement.names}
    return {node.id for node in ast.walk(statement) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
