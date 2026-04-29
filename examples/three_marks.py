"""Inspecting any object across the Three Marks.

Run::

    python examples/three_marks.py
"""

from __future__ import annotations

from buddhism import (
    Conditioned,
    StructuralEq,
    cell,
    derived,
    examine,
    impermanent,
)


class Plain:
    def __init__(self, x: int) -> None:
        self.x = x


class Sheet(Conditioned):
    a = cell(1)
    b = cell(2)

    @derived
    def c(self) -> int:
        return self.a + self.b


class Address(StructuralEq):
    def __init__(self, street: str, city: str) -> None:
        self.street = street
        self.city = city


@impermanent(validity=10.0)
def fetch_rate() -> float:
    return 0.79


def main() -> None:
    print("--- Plain object: sparse view ---")
    print(examine(Plain(5)).text_report())
    print()

    print("--- Sheet (Conditioned): rich Anatta with reactive deps ---")
    s = Sheet()
    _ = s.c  # materialise
    print(examine(s).text_report())
    print()

    print("--- Address (StructuralEq): rich Anatta with structural hash ---")
    print(examine(Address("221B Baker St", "London")).text_report())
    print()

    print("--- @impermanent function: rich Anitya ---")
    print(examine(fetch_rate).text_report())


if __name__ == "__main__":
    main()
