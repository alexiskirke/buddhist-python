"""Auditing a function's effects with @karmic.

Note: ``@karmic`` detects global *rebindings* (``a_module.X = ...``,
``global X; X = ...``) reliably. *Mutations* of an existing mutable global
(e.g. ``cache[k] = v`` where ``cache`` is a global dict) do not change
the binding's identity and are therefore invisible to the snapshot diff.
This is a documented limitation; the same effect is detectable via the
argument-mutation axis if you pass the cache *as an argument*.

Run::

    python examples/karma_audit.py
"""

from __future__ import annotations

from buddhism import KarmicViolation, karmic


# A "registry" stored as a global. We will *rebind* it (replace the
# whole dict) on each write so the audit catches the effect.
registry: dict = {}


@karmic
def register_user(name: str) -> int:
    """A function that secretly mutates module state."""
    global registry
    registry = {**registry, name: len(registry)}
    return registry[name]


@karmic(allow={"global:registry"})
def well_behaved_register(name: str) -> int:
    """Same effect, but the side effect is declared up front."""
    global registry
    registry = {**registry, name: len(registry)}
    return registry[name]


@karmic(allow=set())
def vow_of_purity(x: int) -> int:
    """No globals, no I/O, no argument mutation."""
    return x * 2


@karmic
def append_to_buffer(buf: list, x: int) -> None:
    """Argument mutation — caught via the deepcopy snapshot diff."""
    buf.append(x)


def main() -> None:
    print("--- Audit: who touches what? ---")
    out = register_user("Alice")
    print(f"  register_user('Alice') = {out.value}")
    print(f"  globals_written: {sorted(out.ledger.globals_written)}")
    print(f"  pure?            {out.ledger.is_pure()}")

    print("\n--- Same effect, declared up front ---")
    out2 = well_behaved_register("Bob")
    print(f"  well_behaved_register('Bob') = {out2.value}")
    print(f"  globals_written: {sorted(out2.ledger.globals_written)}")

    print("\n--- A vow of purity that holds ---")
    out3 = vow_of_purity(5)
    print(f"  vow_of_purity(5) = {out3.value}")
    print(f"  pure?            {out3.ledger.is_pure()}")

    print("\n--- Argument mutation: caught by snapshot diff ---")
    buf = [1, 2]
    out4 = append_to_buffer(buf, 99)
    print(f"  buf is now {buf}")
    print(f"  arg_mutations:  {dict(out4.ledger.arg_mutations)}")

    print("\n--- A vow of purity that breaks ---")
    @karmic(allow=set())
    def secretly_impure(x: int) -> int:
        global registry
        registry = {"k": x}
        return x

    try:
        secretly_impure(99)
    except KarmicViolation as e:
        print(f"  KarmicViolation: {e}")


if __name__ == "__main__":
    main()
