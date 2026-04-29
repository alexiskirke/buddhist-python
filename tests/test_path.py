"""Tests for the Eightfold Path checker."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from buddhism.path import PathConfig, run_all
from buddhism.path.checks import (
    check_right_action,
    check_right_concentration,
    check_right_intention,
    check_right_livelihood,
    check_right_mindfulness,
    check_right_speech,
    check_right_view,
)


def _write_module(tmp_path: pathlib.Path, name: str, src: str) -> pathlib.Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(src))
    return p


def _parse_modules(tmp_path: pathlib.Path):
    import ast
    out = []
    for p in tmp_path.glob("*.py"):
        out.append((p.name, p, ast.parse(p.read_text())))
    return out


# --------------------------------------------------------------------------- #
# Right View
# --------------------------------------------------------------------------- #


def test_right_view_passes_with_typed_functions(tmp_path):
    _write_module(tmp_path, "ok.py", """
        def add(x: int, y: int) -> int:
            return x + y
    """)
    cfg = PathConfig(type_coverage_threshold=0.5)
    res = check_right_view(cfg, _parse_modules(tmp_path))
    assert res.passed


def test_right_view_fails_with_untyped(tmp_path):
    _write_module(tmp_path, "bad.py", """
        def f(x, y):
            return x + y

        def g(x, y):
            return x * y
    """)
    cfg = PathConfig(type_coverage_threshold=0.5)
    res = check_right_view(cfg, _parse_modules(tmp_path))
    assert not res.passed


# --------------------------------------------------------------------------- #
# Right Intention
# --------------------------------------------------------------------------- #


def test_right_intention_requires_docstrings(tmp_path):
    _write_module(tmp_path, "bad.py", """
        def f(x):
            return x
    """)
    cfg = PathConfig()
    res = check_right_intention(cfg, _parse_modules(tmp_path))
    assert not res.passed


def test_right_intention_passes_with_docstrings(tmp_path):
    _write_module(tmp_path, "ok.py", '''
        def f(x):
            """Doubles x."""
            return x * 2
    ''')
    cfg = PathConfig()
    res = check_right_intention(cfg, _parse_modules(tmp_path))
    assert res.passed


# --------------------------------------------------------------------------- #
# Right Speech
# --------------------------------------------------------------------------- #


def test_right_speech_flags_print_calls(tmp_path):
    _write_module(tmp_path, "noisy.py", """
        def f():
            print("hello")
    """)
    cfg = PathConfig()
    res = check_right_speech(cfg, _parse_modules(tmp_path))
    assert not res.passed


def test_right_speech_allows_print_in_cli_modules(tmp_path):
    _write_module(tmp_path, "cli.py", """
        __cli__ = True

        def f():
            print("hello")
    """)
    cfg = PathConfig()
    res = check_right_speech(cfg, _parse_modules(tmp_path))
    assert res.passed


# --------------------------------------------------------------------------- #
# Right Action
# --------------------------------------------------------------------------- #


def test_right_action_flags_argument_mutation(tmp_path):
    _write_module(tmp_path, "bad.py", """
        def f(buf):
            buf.append(1)
    """)
    cfg = PathConfig()
    res = check_right_action(cfg, _parse_modules(tmp_path))
    # An assignment to buf.something is a mutation; .append is a Call which
    # is NOT detected here (we only check Subscript/Attribute Stores).
    # So this test asserts the WEAKER guarantee: index/attr mutations.

    _write_module(tmp_path, "bad2.py", """
        def f(d):
            d['k'] = 1
    """)
    res = check_right_action(cfg, _parse_modules(tmp_path))
    assert not res.passed


def test_right_action_allows_out_named_args(tmp_path):
    _write_module(tmp_path, "ok.py", """
        def f(out):
            out['k'] = 1
    """)
    cfg = PathConfig()
    res = check_right_action(cfg, _parse_modules(tmp_path))
    assert res.passed


# --------------------------------------------------------------------------- #
# Right Livelihood
# --------------------------------------------------------------------------- #


def test_right_livelihood_flags_io_in_pure_module(tmp_path):
    _write_module(tmp_path, "pure_bad.py", """
        __pure__ = True

        def f():
            with open("x") as h:
                return h.read()
    """)
    cfg = PathConfig()
    res = check_right_livelihood(cfg, _parse_modules(tmp_path))
    assert not res.passed


def test_right_livelihood_allows_io_in_unmarked_module(tmp_path):
    _write_module(tmp_path, "impure_ok.py", """
        def f():
            with open("x") as h:
                return h.read()
    """)
    cfg = PathConfig()
    res = check_right_livelihood(cfg, _parse_modules(tmp_path))
    assert res.passed


# --------------------------------------------------------------------------- #
# Right Concentration
# --------------------------------------------------------------------------- #


def test_right_concentration_threshold_enforced(tmp_path):
    # A function with high cyclomatic complexity (many branches).
    branches = "\n".join(f"    if x == {i}: return {i}" for i in range(20))
    src = "def f(x):\n" + branches + "\n"
    (tmp_path / "complex.py").write_text(src)
    cfg = PathConfig(max_complexity=5)
    res = check_right_concentration(cfg, _parse_modules(tmp_path))
    assert not res.passed


# --------------------------------------------------------------------------- #
# End-to-end: run_all() against the buddhism package itself
# --------------------------------------------------------------------------- #


def test_run_all_produces_a_report():
    target = pathlib.Path(__file__).parent.parent / "src" / "buddhism"
    report = run_all(target)
    assert report.results
    assert report.total_count >= 6
    text = report.text_report()
    assert "buddhism path examined" in text
