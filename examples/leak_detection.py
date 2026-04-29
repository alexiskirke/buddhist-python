"""Spotting clinging in a function that "looks fine".

Run::

    python examples/leak_detection.py
"""

from __future__ import annotations

import gc

from buddhism.dukkha import (
    Attachment,
    ClingingDetected,
    find_cycles,
    let_go,
    observe,
    retention_path,
)


# --------------------------------------------------------------------------- #
# 1. observe() — what survived the work I just did?
# --------------------------------------------------------------------------- #


class Document:
    def __init__(self, title: str) -> None:
        self.title = title


_audit_log: list = []  # the silent cling


def process(title: str) -> str:
    doc = Document(title)
    _audit_log.append(doc)  # innocent-looking; binds doc to the global
    return doc.title.upper()


def demo_observe() -> None:
    print("--- observe() — diff live objects across a block ---")
    with observe() as report:
        for i in range(5):
            process(f"doc-{i}")
    print(report.text_report())
    print()


# --------------------------------------------------------------------------- #
# 2. let_go — assert a function does not retain its inputs
# --------------------------------------------------------------------------- #


cache: list = []


@let_go
def pure(d: Document) -> str:
    # Touches the input but does not retain it. Returns a derived string.
    return d.title.lower()


@let_go
def leaky(d: Document) -> None:
    # Retains the input via a module-level list — silent clinging.
    cache.append(d)


def demo_let_go() -> None:
    print("--- @let_go — function purity assertion ---")
    print("pure(doc):", pure(Document("hello")))
    try:
        leaky(Document("oops"))
    except ClingingDetected as e:
        print("clinging detected:")
        print(" ", e)
    print()


# --------------------------------------------------------------------------- #
# 3. find_cycles — strongly-connected components in user-level objects
# --------------------------------------------------------------------------- #


def demo_find_cycles() -> None:
    print("--- find_cycles — reference cycles in a small object set ---")

    class Node:
        def __init__(self, label: str) -> None:
            self.label = label

    a = Node("A")
    b = Node("B")
    c = Node("C")
    a.peer = b
    b.peer = c
    c.peer = a  # closes the cycle

    cycles = find_cycles([a, b, c])
    for cyc in cycles:
        print("  cycle:", " ↔ ".join(n.label for n in cyc))
    print()


# --------------------------------------------------------------------------- #
# 4. retention_path — show one path of clinging from a root
# --------------------------------------------------------------------------- #


def demo_retention_path() -> None:
    print("--- retention_path — who is holding this object? ---")
    doc = Document("rooted")
    _audit_log.append(doc)
    att = Attachment(doc)
    doc = None  # noqa: F841
    gc.collect()
    if att.alive:
        path = retention_path(att.get())
        print(f"  retained by chain of {len(path)} object(s):")
        for i, obj in enumerate(path):
            kind = type(obj).__name__
            short = repr(obj)[:60]
            print(f"   [{i}] {kind:>16}  {short}")
    print()


def main() -> None:
    demo_observe()
    demo_let_go()
    demo_find_cycles()
    demo_retention_path()


if __name__ == "__main__":
    main()
