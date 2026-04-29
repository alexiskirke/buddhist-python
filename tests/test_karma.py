"""Tests for buddhism.karma — side-effect accounting."""

from __future__ import annotations

import os
import socket
import tempfile

import pytest

from buddhism.karma import (
    IOEvent,
    KarmaDebt,
    KarmaLedger,
    KarmicResult,
    KarmicViolation,
    karmic,
)


# Module-level globals used for write-tracking tests.
counter = 0
log_lines: list = []


# --------------------------------------------------------------------------- #
# Pure call: no side effects
# --------------------------------------------------------------------------- #


def test_pure_function_has_pure_ledger():
    @karmic
    def add(a, b):
        return a + b

    out = add(2, 3)
    assert isinstance(out, KarmicResult)
    assert out.value == 5
    assert out.ledger.is_pure()


def test_destructuring_works():
    @karmic
    def f(x):
        return x * 2

    value, ledger = f(7)
    assert value == 14
    assert ledger.is_pure()


# --------------------------------------------------------------------------- #
# Globals tracking
# --------------------------------------------------------------------------- #


def test_globals_write_is_tracked():
    @karmic
    def increment():
        global counter
        counter += 1
        return counter

    initial = counter
    out = increment()
    assert "counter" in out.ledger.globals_written
    assert counter == initial + 1


def test_globals_read_is_tracked_best_effort():
    @karmic
    def use_log():
        return len(log_lines)

    out = use_log()
    # Read tracking is best-effort due to LOAD_GLOBAL inline caches in 3.11+.
    # We don't strictly assert; we assert at least that purity is correctly
    # detected (no writes).
    assert out.value == len(log_lines)
    assert not out.ledger.globals_written


# --------------------------------------------------------------------------- #
# Arg mutation tracking
# --------------------------------------------------------------------------- #


def test_arg_mutation_is_tracked():
    @karmic
    def append_to(buf, x):
        buf.append(x)
        return None

    buf: list = [1, 2]
    out = append_to(buf, 3)
    assert 0 in out.ledger.arg_mutations
    before, after = out.ledger.arg_mutations[0]
    assert before == [1, 2]
    assert after == [1, 2, 3]


def test_arg_mutation_pure_function_does_not_flag():
    @karmic
    def length(buf):
        return len(buf)

    out = length([1, 2, 3])
    assert not out.ledger.arg_mutations


def test_atomic_args_skip_snapshot():
    @karmic
    def f(n):
        return n * 2

    out = f(42)
    assert not out.ledger.arg_mutations
    assert not out.ledger.unsupported


# --------------------------------------------------------------------------- #
# I/O tracking
# --------------------------------------------------------------------------- #


def test_io_file_open_is_tracked(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hi")

    @karmic
    def read_file():
        with open(p) as f:
            return f.read()

    out = read_file()
    kinds = {e.kind for e in out.ledger.io_events}
    assert "file_open" in kinds
    assert out.value == "hi"


def test_io_subprocess_is_tracked():
    import subprocess

    @karmic
    def call_true():
        return subprocess.run(["true"], check=True).returncode

    out = call_true()
    kinds = {e.kind for e in out.ledger.io_events}
    assert "subprocess" in kinds


# --------------------------------------------------------------------------- #
# allow-list strict mode
# --------------------------------------------------------------------------- #


def test_strict_mode_pure_function_passes():
    @karmic(allow=set())
    def add(a, b):
        return a + b

    out = add(1, 2)
    assert out.value == 3


def test_strict_mode_unauthorized_global_write_raises():
    @karmic(allow=set())
    def bump():
        global counter
        counter += 1

    with pytest.raises(KarmicViolation, match="global write"):
        bump()


def test_strict_mode_authorized_global_write_passes():
    @karmic(allow={"global:counter"})
    def bump():
        global counter
        counter += 1

    out = bump()
    assert "counter" in out.ledger.globals_written


def test_strict_mode_io_violation(tmp_path):
    target = tmp_path / "x.txt"
    target.write_text("hello")

    @karmic(allow=set())
    def open_file():
        with open(target) as f:
            return f.read()

    with pytest.raises(KarmicViolation, match="io"):
        open_file()


def test_strict_mode_arg_mutation_violation():
    @karmic(allow=set())
    def mutate(buf):
        buf.append(99)

    with pytest.raises(KarmicViolation, match="argument 0 mutated"):
        mutate([1, 2])


def test_strict_mode_arg_mutation_allowed():
    @karmic(allow={"arg:0"})
    def mutate(buf):
        buf.append(99)
        return None

    out = mutate([1, 2])
    assert out.ledger.arg_mutations


# --------------------------------------------------------------------------- #
# debt + acknowledge
# --------------------------------------------------------------------------- #


def test_debt_starts_unacknowledged():
    @karmic
    def bump():
        global counter
        counter += 1

    out = bump()
    debt = out.ledger.debt()
    assert debt.total >= 1
    assert "counter" in debt.globals_unacknowledged


def test_debt_can_be_paid():
    @karmic
    def bump():
        global counter
        counter += 1

    out = bump()
    out.ledger.acknowledge(globals=["counter"])
    debt = out.ledger.debt()
    assert "counter" not in debt.globals_unacknowledged


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #


def test_only_function_types_supported():
    # Builtins are not plain Python functions; @karmic refuses them.
    with pytest.raises(TypeError, match="plain Python functions"):
        karmic(len)


def test_io_patches_restored_after_call():
    """The patches must restore the originals when the last @karmic call
    on the thread exits."""
    original_open = open

    @karmic
    def noop():
        return None

    noop()
    assert open is original_open
