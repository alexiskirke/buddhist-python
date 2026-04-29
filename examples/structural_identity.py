"""Structural identity: value semantics on demand, and `diff` that
distinguishes "this object was mutated" from "this object was replaced".

Run::

    python examples/structural_identity.py
"""

from __future__ import annotations

from buddhism import StructuralEq, diff, without_self


class Address(StructuralEq):
    def __init__(self, street: str, city: str, zipcode: str) -> None:
        self.street = street
        self.city = city
        self.zipcode = zipcode


class Calculator:
    def __init__(self, n: int = 0) -> None:
        self.n = n

    def step(self, by: int) -> int:
        return self.n + by


def main() -> None:
    a1 = Address("221B Baker St", "London", "NW1 6XE")
    a2 = Address("221B Baker St", "London", "NW1 6XE")
    print("--- StructuralEq: value semantics, no boilerplate ---")
    print(f"a1 == a2? {a1 == a2}     a1 is a2? {a1 is a2}")
    print(f"hash(a1) == hash(a2)? {hash(a1) == hash(a2)}")
    s = {a1, a2, Address("10 Downing St", "London", "SW1A 2AA")}
    print(f"set of three references, but only {len(s)} distinct addresses")

    print("\n--- diff: identity vs configuration ---")
    same = diff(a1, a1)
    cloned = diff(a1, a2)
    a3 = Address("222 Baker St", "London", "NW1")
    different = diff(a1, a3)
    print(f"a1 vs a1:    {same.summary()}")
    print(f"a1 vs a2:    {cloned.summary()}")
    print(f"a1 vs a3:    {different.summary()}")
    print(f"  changed fields: {different.field_changes}")

    print("\n--- without_self: methods as pure functions ---")
    pure_step = without_self(Calculator.step)
    print(f"pure_step({{'n': 10}}, 5) = {pure_step({'n': 10}, 5)}")
    print(f"pure_step({{'n': 100}}, 7) = {pure_step({'n': 100}, 7)}")
    # No instance ever existed.


if __name__ == "__main__":
    main()
