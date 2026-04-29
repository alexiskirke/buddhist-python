"""Koan 06 — Karma.

  "Beings are owners of their karma, heirs of their karma."
                                          — Aṅguttara Nikāya 5.57

Python feature: side-effect tracing via globals substitution, builtins
patching, and ``copy.deepcopy`` snapshots, all coordinated by the
:func:`buddhism.karma.karmic` decorator.

The principle: the trace of an action survives the action. We can make
that trace structured and queryable rather than implicit.
"""

from __future__ import annotations

from buddhism.karma import (
    KarmaLedger,
    KarmicResult,
    KarmicViolation,
    karmic,
    pure,
)

from buddhism.karma import pure
from . import __  # noqa: F401

TITLE = "Karma — actions, traced."

HINT = (
    "@karmic returns (value, ledger). The ledger names every observed "
    "side effect: globals written, I/O events, arguments mutated. "
    "@karmic(allow=set()) raises KarmicViolation on anything outside the "
    "allow-list — the runtime equivalent of a vow."
)


_state = {"counter": 0}


@pure
def _step_pure_function_has_pure_ledger() -> None:
    @karmic
    def add(a: int, b: int) -> int:
        return a + b

    out = add(2, 3)
    assert isinstance(out, KarmicResult)
    assert out.value == 5
    assert out.ledger.is_pure()


@pure
def _step_destructuring_works() -> None:
    @karmic
    def square(x: int) -> int:
        return x * x

    value, ledger = square(7)
    assert value == 49
    assert ledger.is_pure()


@pure
def _step_argument_mutation_is_tracked() -> None:
    @karmic
    def append_to(buf: list, item: int) -> None:
        buf.append(item)

    buf = [1, 2]
    out = append_to(buf, 3)
    assert 0 in out.ledger.arg_mutations
    before, after = out.ledger.arg_mutations[0]
    assert before == [1, 2]
    assert after == [1, 2, 3]


@pure
def _step_strict_mode_refuses_unauthorized_writes() -> None:
    @karmic(allow=set())
    def add(a: int, b: int) -> int:
        return a + b  # truly pure

    out = add(1, 2)
    assert out.value == 3

    @karmic(allow=set())
    def writes_global() -> None:
        global _state
        _state = {"counter": 1}

    raised = False
    try:
        writes_global()
    except KarmicViolation:
        raised = True
    assert raised


@pure
def _step_debt_can_be_acknowledged() -> None:
    @karmic
    def writes_global() -> None:
        # Rebinding the global (rather than mutating the dict it points
        # at) is what creates a *write* visible to karma's snapshot diff.
        global _state
        _state = {"counter": _state["counter"] + 1}

    out = writes_global()
    debt = out.ledger.debt()
    assert debt.total >= 1

    out.ledger.acknowledge(globals=["_state"])
    debt_after = out.ledger.debt()
    assert "_state" not in debt_after.globals_unacknowledged


@pure
def KOAN() -> None:
    """Run all steps of this koan; raises AssertionError on first failure."""
    _step_pure_function_has_pure_ledger()
    _step_destructuring_works()
    _step_argument_mutation_is_tracked()
    _step_strict_mode_refuses_unauthorized_writes()
    _step_debt_can_be_acknowledged()
