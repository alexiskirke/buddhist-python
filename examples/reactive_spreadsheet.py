"""Reactive spreadsheet: a class is a sheet, attributes are cells.

Run::

    python examples/reactive_spreadsheet.py
"""

from __future__ import annotations

from buddhism import Conditioned, batch, cell, derived, on_change


class Invoice(Conditioned):
    quantity = cell(1)
    unit_price = cell(10.0)
    tax_rate = cell(0.20)
    discount = cell(0.0)

    @derived
    def subtotal(self) -> float:
        return self.quantity * self.unit_price

    @derived
    def discounted(self) -> float:
        return self.subtotal * (1 - self.discount)

    @derived
    def tax(self) -> float:
        return self.discounted * self.tax_rate

    @derived
    def total(self) -> float:
        return self.discounted + self.tax


def main() -> None:
    inv = Invoice()

    # Force the `total` Derived to materialise so we can subscribe to its node.
    _ = inv.total
    nodes = inv.__pratitya_nodes__()
    on_change(
        nodes["total"],
        lambda old, new: print(f"  total changed: {old:.2f} → {new:.2f}"),
    )

    print("--- initial conditions ---")
    print(f"  qty={inv.quantity}  price={inv.unit_price}  tax={inv.tax_rate}")
    print(f"  total = {inv.total:.2f}")

    print("\n--- single update: quantity 1 → 3 ---")
    inv.quantity = 3

    print("\n--- batched update (only one notification, not three) ---")
    with batch():
        inv.quantity = 10
        inv.unit_price = 25.0
        inv.discount = 0.10

    print(f"\nFinal total = {inv.total:.2f}")


if __name__ == "__main__":
    main()
