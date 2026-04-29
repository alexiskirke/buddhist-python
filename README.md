# buddhist-python

> *"When this is, that is. From the arising of this, that arises."*
> — Saṃyutta Nikāya 12.61

Buddhist concepts as **load-bearing** Python infrastructure — not a rename
layer, but a small set of doctrinal ideas implemented at the deepest leverage
points of the language.

```python
from buddhism import Conditioned, cell, derived

class Invoice(Conditioned):
    quantity   = cell(1)
    unit_price = cell(10.0)
    tax_rate   = cell(0.20)

    @derived
    def subtotal(self): return self.quantity * self.unit_price

    @derived
    def total(self):    return self.subtotal * (1 + self.tax_rate)

inv = Invoice()
inv.total          # 12.0
inv.quantity = 5
inv.total          # 60.0  ← arose anew from the new conditions
```

No manual recompute. No invalidation flags. No publish/subscribe ceremony.
The values arise from their conditions and re-arise when the conditions
change. That's it.

---

## Why this exists

Most "philosophy-themed" libraries rename a `for` loop and call it
enlightenment. This package picks four ideas from Buddhist philosophy that
already correspond, *technically*, to specific things Python can do:

| Doctrine                     | Python primitive                         | Module                             |
|------------------------------|------------------------------------------|------------------------------------|
| **Pratītyasamutpāda**<br>*Dependent Origination* | descriptors + auto-tracked dependency graph | [`buddhism.pratitya`](#1-pratitya--dependent-origination) |
| **Dukkha**<br>*Clinging / unsatisfactoriness* | `gc` + `weakref` retention analysis | [`buddhism.dukkha`](#2-dukkha--the-profiler-of-clinging) |
| **Anitya**<br>*Impermanence* | TTL containers, decay caches *(v0.2)*   | `buddhism.anitya` *(roadmap)*      |
| **Anatta**<br>*Non-self*    | identity / equality / `__dict__`         | taught in [Koan 03](#3-koans--a-tutorial-track) |

The thesis: a value defined by relationships, a leak defined as clinging,
and a tutorial that teaches both Python internals and the corresponding
philosophy — that's a coherent, useful, and *honestly* Buddhist Python
package.

---

## Install

```bash
pip install buddhist-python
```

Python 3.9+. No runtime dependencies.

---

## 1. `pratitya` — Dependent Origination

A reactive dependency graph. Two surfaces:

### Standalone signals

```python
from buddhism import Cell, derive

a = Cell(1)
b = Cell(2)
c = derive(lambda: a() + b())     # auto-tracks dependence on a, b
c()                                # 3
a.set(10);  c()                    # 12
```

### Class-attribute descriptors (the spreadsheet form)

```python
from buddhism import Conditioned, cell, derived, on_change, batch

class Triangle(Conditioned):
    base   = cell(3.0)
    height = cell(4.0)

    @derived
    def area(self):
        return 0.5 * self.base * self.height

t = Triangle()
t.area                # 6.0
t.base = 6
t.area                # 12.0
```

### What's actually deep about it

* **Auto-tracked dependencies via `ContextVar`.** Reading a `Cell` while a
  `Derived` is being evaluated records an edge. Two updates to two different
  conditions don't double-count: the dependency set is rebuilt on each
  recomputation, so dead branches stop counting.

* **Pull-based, with eager subscribers.** `Derived` values are dirty-flagged
  on invalidation and only recomputed when read. `on_change(node, callback)`
  gives you eager notification *if* you want it. You don't pay for
  subscribers you didn't ask for.

* **The graph itself does not cling.** Edges from a `Cell` to its dependents
  are stored in a `WeakSet`. If your `Derived` becomes unreachable, the GC
  collects it, and the cell's edge dies with it — no manual unsubscribe.

* **Dynamic, not declared.** `chosen` only depends on `b` while `a` is True;
  flip `a` and the graph reorganises. Conditions change; relationships change.

* **Conditional cycles raise `SamsaraError`.** A → B → A has no still point
  at which to assign a value, and we say so out loud.

* **`with batch():`** coalesces multiple writes so each subscriber fires at
  most once, with the correct *before* and *after* values, after the cascade
  completes.

```python
with batch():
    inv.quantity   = 10
    inv.unit_price = 25
    inv.discount   = 0.10
# subscriber on `inv.total` fires once, with the pre-batch and post-batch totals
```

---

## 2. `dukkha` — The profiler of clinging

> *We don't fail to release because objects refuse — we hold them ourselves.
> The garbage collector is willing.*

A practical leak detector built on `gc` + `weakref`.

### `observe()` — diff live objects across a block

```python
from buddhism.dukkha import observe

with observe() as report:
    do_some_work()

print(report.text_report())
# 7 object(s) retained after the block. (0 reference cycle(s) detected.)
#
# Top retained types:
#     5  Document
#     2  set
```

### `@let_go` — assert a function does not retain its inputs

```python
from buddhism.dukkha import let_go

@let_go
def pure(d): return d.title.upper()      # OK

@let_go
def leaky(d): cache.append(d)            # raises ClingingDetected
```

### `find_cycles` — strongly-connected components in your object set

```python
cycles = find_cycles([a, b, c])          # [[a, b, c]] for a → b → c → a
```

### `retention_path` — *who* is holding this?

```python
att = Attachment(doc)
del doc; gc.collect()
if att.alive:
    for i, obj in enumerate(retention_path(att.get())):
        print(f"  [{i}] {type(obj).__name__:>16}  {obj!r:.60}")
# [0]             type  <class '__main__.Document'>
# [1]             dict  ...
# [2]             list  ...
# [3]         Document  <__main__.Document object at 0x…>
```

You read it from the root down to the bottom. That's the *thread of
clinging*.

---

## 3. `koans` — a tutorial track

Five short modules pair one Buddhist concept with one deep Python feature
as a series of small, runnable assertions:

| | |
|---|---|
| **01** | **Impermanence** — mutation, aliasing, the mutable-default-argument trap |
| **02** | **Dependent Origination** — `pratitya` in anger |
| **03** | **Non-Self** — identity vs equality, `__dict__`, descriptors |
| **04** | **Clinging** — `weakref`, `gc`, `dukkha` |
| **05** | **Emptiness** — `None`, sentinels, falsy values |

Run the whole track:

```bash
python -m buddhism.koans
# ✓ k01_impermanence
# ✓ k02_dependent_origination
# ✓ k03_non_self
# ✓ k04_clinging
# ✓ k05_emptiness
#
# All koans completed.
```

The koans are *passing by default* — they're a guided tour. To turn them
into self-tests, replace any literal answer with `__` (imported from
`buddhism.koans`) and re-run:

```python
# k01_impermanence.py
def _step_rebind_does_not_mutate():
    a = [1, 2, 3]
    b = a
    a = a + [4]
    assert b == __     # ← replace with the right answer
```

The runner stops at the first failure, prints the file:line, and shows
the koan's hint.

---

## Examples

```bash
python examples/reactive_spreadsheet.py     # invoice with cascading recompute
python examples/reactive_config.py          # config object whose derived paths re-arise
python examples/leak_detection.py           # observe(), @let_go, find_cycles, retention_path
```

---

## Roadmap

**v0.1** *(this release)* — Dependent Origination, Clinging, Koans.

**v0.2** — *Anitya*, the policy layer of impermanence:

* TTL-decay containers
* LRU-with-forgetting
* memory-pressure "letting-go" (drop-on-load)

**v0.3** — *Karma*, side-effect auditing:

* AST/bytecode purity analysis
* per-function "karmic debt" report (which globals were touched, which I/O occurred)
* opt-in enforcement decorator

**v0.4** — *Anatta* tools: structural-equality types, identity-aware hashing.

---

## Design principles

1. **Doctrinal, not decorative.** Every Buddhist term in the public API
   maps to a real Python primitive. If we couldn't justify it as engineering,
   we didn't ship it.
2. **Non-clinging by default.** The library itself uses `WeakSet` and
   `weakref` so its own data structures don't become a source of dukkha.
3. **Pure-Python, no dependencies.** Should work the same on CPython 3.9+
   on every platform.
4. **Tests are the doctrine.** See `tests/`.

---

## Contributing

PRs welcome. Especially:

* additional koans (one new Buddhist concept paired with one deep Python feature)
* corner-case tests for `pratitya` (cycles, threading, asyncio)
* visualisation of retention graphs in `dukkha`

---

## License

MIT — see [LICENSE](LICENSE).

---

> *"Whatever has the nature of arising, all that has the nature of cessation."*
>                                          — Aññāsi-Koṇḍañña, on the first sermon
