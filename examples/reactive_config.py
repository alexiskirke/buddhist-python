"""A reactive config object: change a base setting, derived ones recompute.

A practical pattern: configuration where some fields are computed from
others (e.g. log-file path is a function of base-dir and service name).
With pratitya, derivations stay correct without manual invalidation.

Run::

    python examples/reactive_config.py
"""

from __future__ import annotations

import os.path

from buddhism import Conditioned, batch, cell, derived, on_change


class Config(Conditioned):
    base_dir = cell("/var/app")
    service = cell("api")
    env = cell("dev")

    @derived
    def log_dir(self) -> str:
        return os.path.join(self.base_dir, "logs", self.service)

    @derived
    def log_file(self) -> str:
        return os.path.join(self.log_dir, f"{self.env}.log")

    @derived
    def db_url(self) -> str:
        return f"postgres://localhost/{self.service}_{self.env}"


def main() -> None:
    cfg = Config()
    _ = cfg.log_file  # materialise the node so we can subscribe
    on_change(
        cfg.__pratitya_nodes__()["log_file"],
        lambda old, new: print(f"  log_file: {old} → {new}"),
    )

    print("initial:")
    print(f"  log_file = {cfg.log_file}")
    print(f"  db_url   = {cfg.db_url}")

    print("\nflip env to 'prod':")
    cfg.env = "prod"

    print("\nrename service AND change base in one batch:")
    with batch():
        cfg.service = "billing"
        cfg.base_dir = "/srv/app"

    print(f"\nfinal log_file = {cfg.log_file}")
    print(f"final db_url   = {cfg.db_url}")


if __name__ == "__main__":
    main()
