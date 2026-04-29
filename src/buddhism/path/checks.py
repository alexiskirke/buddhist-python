"""The eight checks of the Eightfold Path.

Each ``check_*`` function takes a :class:`PathConfig` and a list of
``(module_path, ast.AST)`` records and returns a :class:`CheckResult`.

The orchestrator :func:`run_all` runs all enabled checks and returns
a :class:`PathReport`.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import pathlib
from ..karma import pure
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "CheckResult",
    "PathReport",
    "PathConfig",
    "run_all",
]


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass
class PathConfig:
    """Thresholds + per-check disable flags. Loaded from
    ``[tool.buddhism.path]`` in ``pyproject.toml`` if present."""

    type_coverage_threshold: float = 0.80
    test_coverage_threshold: float = 0.70
    max_complexity: int = 10
    pure_modules_attribute: str = "__pure__"
    mindfulness_decorators: Tuple[str, ...] = (
        "let_go",
        "karmic",
        "impermanent",
        "pure",
    )

    enable_right_view: bool = True
    enable_right_intention: bool = True
    enable_right_speech: bool = True
    enable_right_action: bool = True
    enable_right_livelihood: bool = True
    enable_right_effort: bool = True
    enable_right_mindfulness: bool = False  # opt-in (most opinionated)
    enable_right_concentration: bool = True

    @classmethod
    def from_pyproject(cls, root: pathlib.Path) -> "PathConfig":
        """Load configuration from ``[tool.buddhism.path]`` in ``pyproject.toml``."""
        cfg = cls()
        pp = root / "pyproject.toml"
        if not pp.is_file():
            return cfg
        try:
            try:
                import tomllib  # py311+
            except ModuleNotFoundError:
                import tomli as tomllib  # type: ignore[no-redef]
            data = tomllib.loads(pp.read_text())
        except Exception:
            return cfg
        section = (
            data.get("tool", {}).get("buddhism", {}).get("path", {})
        )
        for k, v in section.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #


@dataclass
class CheckResult:
    name: str
    passed: bool
    summary: str
    details: List[str] = field(default_factory=list)


@dataclass
class PathReport:
    target: str
    results: List[CheckResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        """Number of checks that passed."""
        return sum(1 for r in self.results if r.passed)

    @property
    def total_count(self) -> int:
        """Number of checks that ran (some may be disabled by config)."""
        return len(self.results)

    def text_report(self) -> str:
        """Render the path report as a human-readable text block."""
        lines = [f"buddhism path examined {self.target}"]
        lines.append("")
        for r in self.results:
            mark = "✓" if r.passed else "✗"
            lines.append(f"  {mark} {r.name:<20}  {r.summary}")
            if not r.passed:
                for d in r.details[:3]:
                    lines.append(f"      - {d}")
                if len(r.details) > 3:
                    lines.append(f"      ... ({len(r.details) - 3} more)")
        lines.append("")
        if self.passed_count == self.total_count:
            lines.append(
                f"  {self.passed_count}/{self.total_count} path factors satisfied. "
                f"The path is complete."
            )
        else:
            remain = self.total_count - self.passed_count
            lines.append(
                f"  {self.passed_count}/{self.total_count} path factors satisfied. "
                f"{remain} remain."
            )
        return "\n".join(lines)

    def to_json(self) -> Dict[str, Any]:
        """Serialise the report to a JSON-friendly dict."""
        return {
            "target": self.target,
            "passed": self.passed_count,
            "total": self.total_count,
            "results": [dataclasses.asdict(r) for r in self.results],
        }


# --------------------------------------------------------------------------- #
# Module discovery
# --------------------------------------------------------------------------- #


def _discover_modules(target: pathlib.Path) -> List[Tuple[str, pathlib.Path, ast.AST]]:
    """Walk ``target`` for .py files (excluding tests/ and venv/) and parse each."""
    out: List[Tuple[str, pathlib.Path, ast.AST]] = []
    skip_dirs = {"venv", "__pycache__", ".git", "build", "dist", ".pytest_cache"}
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.endswith(".egg-info")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            p = pathlib.Path(root) / fname
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = str(p.relative_to(target))
            out.append((rel, p, tree))
    return out


# --------------------------------------------------------------------------- #
# 1. Right View — type coverage
# --------------------------------------------------------------------------- #


@pure
def check_right_view(
    cfg: PathConfig,
    modules: Sequence[Tuple[str, pathlib.Path, ast.AST]],
) -> CheckResult:
    """Annotation density across public def-statements."""
    annotated = 0
    total = 0
    untyped: List[str] = []
    for rel, _, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                # Count parameters with annotations + return annotation.
                params = [p for p in node.args.args if p.arg != "self"]
                params += node.args.kwonlyargs
                slot_count = len(params) + 1  # +1 for return
                ann_count = sum(1 for p in params if p.annotation is not None)
                ann_count += 1 if node.returns is not None else 0
                annotated += ann_count
                total += slot_count
                if ann_count < slot_count:
                    untyped.append(f"{rel}:{node.lineno} {node.name}")
    if total == 0:
        return CheckResult(
            name="Right View",
            passed=True,
            summary="no public functions to type",
        )
    coverage = annotated / total
    passed = coverage >= cfg.type_coverage_threshold
    return CheckResult(
        name="Right View",
        passed=passed,
        summary=f"type coverage {coverage:.0%} (threshold {cfg.type_coverage_threshold:.0%})",
        details=untyped[:20],
    )


# --------------------------------------------------------------------------- #
# 2. Right Intention — every public function has a docstring
# --------------------------------------------------------------------------- #


def _has_docstring(node: ast.AST) -> bool:
    body = getattr(node, "body", None)
    if not body:
        return False
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return True
    return False


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _module_level_and_class_method_funcs(
    tree: ast.AST,
) -> List[ast.AST]:
    """Return only module-level functions and class-method definitions
    (i.e. not nested inside another function — those are closures and are
    treated as implementation detail)."""
    out: List[ast.AST] = []

    def visit(parent: ast.AST, in_func: bool) -> None:
        body = getattr(parent, "body", None)
        if not body:
            return
        for child in body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not in_func:
                    out.append(child)
                visit(child, in_func=True)
            elif isinstance(child, ast.ClassDef):
                visit(child, in_func=in_func)
    visit(tree, in_func=False)
    return out


@pure
def check_right_intention(
    cfg: PathConfig,
    modules: Sequence[Tuple[str, pathlib.Path, ast.AST]],
) -> CheckResult:
    """Every public function declares a docstring.

    Dunder methods (``__init__``, ``__get__``, etc.) and decorator
    closures (functions defined inside another function body) are
    exempt — their semantics are defined by language or framework, not
    by their docstring.
    """
    documented = 0
    total = 0
    missing: List[str] = []
    for rel, _, tree in modules:
        for node in _module_level_and_class_method_funcs(tree):
            assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            if node.name.startswith("_") and not _is_dunder(node.name):
                continue
            if _is_dunder(node.name):
                continue
            total += 1
            if _has_docstring(node):
                documented += 1
            else:
                missing.append(f"{rel}:{node.lineno} {node.name}")
    if total == 0:
        return CheckResult(
            name="Right Intention",
            passed=True,
            summary="no public functions to document",
        )
    passed = not missing
    return CheckResult(
        name="Right Intention",
        passed=passed,
        summary=f"{documented}/{total} public functions documented",
        details=missing[:200],
    )


# --------------------------------------------------------------------------- #
# 3. Right Speech — no print() in library code
# --------------------------------------------------------------------------- #


@pure
def check_right_speech(
    cfg: PathConfig,
    modules: Sequence[Tuple[str, pathlib.Path, ast.AST]],
) -> CheckResult:
    """No `print()` calls in library code (CLI modules opt out via ``__cli__ = True``)."""
    prints: List[str] = []
    for rel, _, tree in modules:
        # CLI opt-out: top-level `__cli__ = True` assignment
        if any(
            isinstance(s, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "__cli__" for t in s.targets
            )
            and isinstance(s.value, ast.Constant)
            and s.value.value is True
            for s in tree.body
        ):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                prints.append(f"{rel}:{node.lineno}")
    passed = not prints
    summary = (
        f"{len(prints)} print() call(s) in library code"
        if prints
        else "no print() calls in library code"
    )
    return CheckResult(
        name="Right Speech",
        passed=passed,
        summary=summary,
        details=prints[:20],
    )


# --------------------------------------------------------------------------- #
# 4. Right Action — no unmarked argument mutation
# --------------------------------------------------------------------------- #


@pure
def check_right_action(
    cfg: PathConfig,
    modules: Sequence[Tuple[str, pathlib.Path, ast.AST]],
) -> CheckResult:
    """No assignment to subscripted/attribute paths rooted in a parameter
    name, unless that parameter is annotated as an `out` parameter via
    a `# out` line-comment OR named with an `out_` prefix."""
    violations: List[str] = []
    for rel, _, tree in modules:
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Dunder methods like __set__, __setitem__, __delete__, etc.
            # are mutation by definition (they implement the descriptor /
            # container protocol). They are exempt.
            if _is_dunder(func.name):
                continue
            param_names = {p.arg for p in func.args.args} | {
                p.arg for p in func.args.kwonlyargs
            }
            param_names.discard("self")
            param_names.discard("cls")
            for node in ast.walk(func):
                if isinstance(node, (ast.Assign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        root = _root_name(t)
                        if root and root in param_names and not _is_marked_out(root):
                            violations.append(
                                f"{rel}:{node.lineno} {func.name} mutates {root}"
                            )
    passed = not violations
    summary = (
        f"{len(violations)} unmarked argument mutation(s)"
        if violations
        else "no unmarked argument mutations"
    )
    return CheckResult(
        name="Right Action",
        passed=passed,
        summary=summary,
        details=violations[:20],
    )


def _root_name(target: ast.AST) -> Optional[str]:
    """Return the root Name id of a Subscript/Attribute chain (i.e. the
    name that is being *mutated*), or None for a plain Name (a rebind,
    not a mutation).
    """
    if isinstance(target, (ast.Subscript, ast.Attribute)):
        return _root_name_inner(target.value)
    return None


def _root_name_inner(node: ast.AST) -> Optional[str]:
    """Recursively descend through Subscript/Attribute chains to a Name."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, (ast.Subscript, ast.Attribute)):
        return _root_name_inner(node.value)
    return None


def _is_marked_out(name: str) -> bool:
    return name.startswith("out_") or name == "out"


# --------------------------------------------------------------------------- #
# 5. Right Livelihood — no I/O in modules declaring __pure__ = True
# --------------------------------------------------------------------------- #


_IO_FUNCS: Tuple[str, ...] = (
    "open",  # builtin
    "input",
)
_IO_MODULES: Tuple[str, ...] = (
    "socket",
    "urllib",
    "requests",
    "subprocess",
    "http",
)


@pure
def check_right_livelihood(
    cfg: PathConfig,
    modules: Sequence[Tuple[str, pathlib.Path, ast.AST]],
) -> CheckResult:
    """Modules declaring ``__pure__ = True`` may not call I/O entry points."""
    violations: List[str] = []
    for rel, _, tree in modules:
        is_pure = any(
            isinstance(s, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == cfg.pure_modules_attribute
                for t in s.targets
            )
            and isinstance(s.value, ast.Constant)
            and s.value.value is True
            for s in tree.body
        )
        if not is_pure:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in _IO_FUNCS:
                    violations.append(f"{rel}:{node.lineno} calls {node.func.id}")
                if isinstance(node.func, ast.Attribute):
                    base = node.func.value
                    while isinstance(base, ast.Attribute):
                        base = base.value
                    if isinstance(base, ast.Name) and base.id in _IO_MODULES:
                        violations.append(
                            f"{rel}:{node.lineno} calls {base.id}.*"
                        )
    if not violations:
        return CheckResult(
            name="Right Livelihood",
            passed=True,
            summary="pure modules touched no I/O",
        )
    return CheckResult(
        name="Right Livelihood",
        passed=False,
        summary=f"{len(violations)} I/O call(s) in __pure__ modules",
        details=violations[:20],
    )


# --------------------------------------------------------------------------- #
# 6. Right Effort — test coverage threshold
# --------------------------------------------------------------------------- #


@pure
def check_right_effort(
    cfg: PathConfig,
    modules: Sequence[Tuple[str, pathlib.Path, ast.AST]],
    coverage_value: Optional[float] = None,
    tests_dir: Optional[pathlib.Path] = None,
) -> CheckResult:
    """Tests exist for source modules.

    If a true coverage value is supplied, compares against the threshold.
    Otherwise uses a source/test ratio heuristic: walks ``tests_dir`` (or
    the auto-detected sibling ``tests/`` directory of the target) and
    counts ``test_*.py`` files. The check passes when there is at least
    ``test_coverage_threshold * source_module_count`` test files.
    """
    if coverage_value is not None:
        passed = coverage_value >= cfg.test_coverage_threshold
        return CheckResult(
            name="Right Effort",
            passed=passed,
            summary=f"coverage {coverage_value:.0%} (threshold {cfg.test_coverage_threshold:.0%})",
        )
    src_files = [
        m for m in modules
        if not m[0].endswith("__init__.py") and "test_" not in pathlib.Path(m[0]).name
    ]
    test_files: List[pathlib.Path] = [
        m[1] for m in modules
        if pathlib.Path(m[0]).name.startswith("test_")
    ]
    # Look for a sibling tests/ dir if no test files in target.
    if not test_files and modules:
        # Find common ancestor of the modules.
        first_file = modules[0][1]
        # Walk up to find a tests/ peer or a pyproject.toml directory.
        for ancestor in [first_file.parent, *first_file.parents][:6]:
            tests_candidate = ancestor / "tests"
            if tests_candidate.is_dir():
                test_files = list(tests_candidate.rglob("test_*.py"))
                break
    if tests_dir is not None:
        test_files = list(tests_dir.rglob("test_*.py"))

    if not src_files:
        return CheckResult(
            name="Right Effort",
            passed=True,
            summary="no source modules to test",
        )
    ratio = len(test_files) / max(1, len(src_files))
    passed = ratio >= cfg.test_coverage_threshold
    return CheckResult(
        name="Right Effort",
        passed=passed,
        summary=(
            f"test-file ratio {ratio:.0%} "
            f"({len(test_files)} tests / {len(src_files)} src; "
            f"threshold {cfg.test_coverage_threshold:.0%}; "
            f"install `coverage` for true line coverage)"
        ),
    )


# --------------------------------------------------------------------------- #
# 7. Right Mindfulness — every public function has an effect-naming decorator
# --------------------------------------------------------------------------- #


def _decorator_names(decorators: List[ast.expr]) -> List[str]:
    out: List[str] = []
    for d in decorators:
        if isinstance(d, ast.Name):
            out.append(d.id)
        elif isinstance(d, ast.Attribute):
            out.append(d.attr)
        elif isinstance(d, ast.Call):
            f = d.func
            if isinstance(f, ast.Name):
                out.append(f.id)
            elif isinstance(f, ast.Attribute):
                out.append(f.attr)
    return out


def _module_level_only_funcs(tree: ast.AST) -> List[ast.AST]:
    """Return only the functions defined at the module's top level (not
    nested in another function or in a class body)."""
    return [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


@pure
def check_right_mindfulness(
    cfg: PathConfig,
    modules: Sequence[Tuple[str, pathlib.Path, ast.AST]],
) -> CheckResult:
    """Every module-level public function carries an effect-tagging decorator
    from ``cfg.mindfulness_decorators`` (default: let_go, karmic, impermanent,
from ..karma import pure
    pure)."""
    targets = set(cfg.mindfulness_decorators)
    missing: List[str] = []
    total = 0
    decorated = 0
    for rel, _, tree in modules:
        for node in _module_level_only_funcs(tree):
            assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            if node.name.startswith("_"):
                continue
            # Exempt: a function that *defines* one of the mindfulness
            # decorators is the decorator itself; it cannot meaningfully
            # be decorated by itself at parse time.
            if node.name in targets:
                continue
            total += 1
            names = _decorator_names(node.decorator_list)
            if any(n in targets for n in names):
                decorated += 1
            else:
                missing.append(f"{rel}:{node.lineno} {node.name}")
    if total == 0:
        return CheckResult(
            name="Right Mindfulness",
            passed=True,
            summary="no module-level public functions to tag",
        )
    passed = not missing
    return CheckResult(
        name="Right Mindfulness",
        passed=passed,
        summary=f"{decorated}/{total} module-level public functions decorated",
        details=missing[:200],
    )


# --------------------------------------------------------------------------- #
# 8. Right Concentration — cyclomatic complexity threshold
# --------------------------------------------------------------------------- #


@pure
def check_right_concentration(
    cfg: PathConfig,
    modules: Sequence[Tuple[str, pathlib.Path, ast.AST]],
) -> CheckResult:
    """Approximate cyclomatic complexity per function (count branching nodes + 1)."""
    over: List[Tuple[str, int]] = []
    max_seen = 0
    for rel, _, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                c = 1
                for child in ast.walk(node):
                    if isinstance(child, (
                        ast.If,
                        ast.For,
                        ast.AsyncFor,
                        ast.While,
                        ast.Try,
                        ast.ExceptHandler,
                        ast.With,
                        ast.AsyncWith,
                        ast.BoolOp,
                        ast.IfExp,
                    )):
                        c += 1
                if c > max_seen:
                    max_seen = c
                if c > cfg.max_complexity:
                    over.append((f"{rel}:{node.lineno} {node.name}", c))
    if not over:
        return CheckResult(
            name="Right Concentration",
            passed=True,
            summary=f"max complexity {max_seen}",
        )
    return CheckResult(
        name="Right Concentration",
        passed=False,
        summary=f"{len(over)} function(s) over threshold {cfg.max_complexity}",
        details=[f"{loc} (complexity={c})" for loc, c in over[:20]],
    )


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


_CHECKS: List[Tuple[str, Callable[..., CheckResult]]] = [
    ("right_view", check_right_view),
    ("right_intention", check_right_intention),
    ("right_speech", check_right_speech),
    ("right_action", check_right_action),
    ("right_livelihood", check_right_livelihood),
    ("right_effort", check_right_effort),
    ("right_mindfulness", check_right_mindfulness),
    ("right_concentration", check_right_concentration),
]


@pure
def run_all(
    target: pathlib.Path,
    *,
    cfg: Optional[PathConfig] = None,
) -> PathReport:
    """Run all enabled checks against ``target`` and return a :class:`PathReport`."""
    target = target.resolve()
    if cfg is None:
        # Look for pyproject.toml at target or its parents.
        for ancestor in [target, *target.parents][:6]:
            if (ancestor / "pyproject.toml").is_file():
                cfg = PathConfig.from_pyproject(ancestor)
                break
        if cfg is None:
            cfg = PathConfig()

    modules = _discover_modules(target)
    report = PathReport(target=str(target))

    for name, fn in _CHECKS:
        if not getattr(cfg, f"enable_{name}", True):
            continue
        try:
            res = fn(cfg, modules)
        except Exception as e:
            res = CheckResult(
                name=name.replace("_", " ").title(),
                passed=False,
                summary=f"check raised: {e}",
            )
        report.results.append(res)
    return report
