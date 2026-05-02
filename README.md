# buddhist-python

A Python package providing **decay containers, a side-effect ledger, structural identity
tools, a reactive dependency graph, a retention profiler,  runtime three-marks introspection, 
and a project-quality checker** — dependency-free, in roughly 2,000 lines of Python.

```python
from buddhism import impermanent, Stale, StalenessError
from buddhism import karmic, KarmicViolation

@impermanent(validity=30.0)
def fetch_rate() -> float:
    return external_api.get_rate()

result = fetch_rate()
# Inside 30s: returns float directly.
# After 30s:
match result:
    case Stale(): result = result.refresh()   # re-call
    # or:
    # result = result.accept_stale()           # explicit acknowledgement
    # or just bare access — that raises StalenessError, by design.

@karmic
def update_record(record, value):
    record["v"] = value
    return record["v"]

result, ledger = update_record({"v": 0}, 7)
ledger.arg_mutations   # {0: ({'v': 0}, {'v': 7})}
ledger.is_pure()       # False
```

> The doctrinal labels (Buddhist concepts) are how the package's pieces
> are *named* — they map one-to-one to the engineering primitives. The
> mapping is load-bearing, not decorative. See
> [§ Doctrinal mapping](#doctrinal-mapping-the-design-philosophy) below
> if you'd like to read the design as philosophy. The rest of this
> README reads it as engineering.

---

## Install

```bash
pip install buddhist-python
```

Python 3.9+. No runtime dependencies.

---

## What's in the box

| Module                                  | What it does                                                      |
|-----------------------------------------|--------------------------------------------------------------------|
| [`pratitya`](#1-pratitya--reactive-dependency-graph) | Reactive dependency graph (descriptors + auto-tracking + weakref). |
| [`dukkha`](#2-dukkha--retention-profiler) | Retention profiler (`gc` + `weakref` + Tarjan SCC).               |
| [`anitya`](#3-anitya--decay-containers-and-validity-windows) | `DecayDict`, `@impermanent`, `MemoryPressureRegistry`.            |
| [`anatta`](#4-anatta--structural-identity-tools) | `StructuralEq`, `without_self`, `diff`.                            |
| [`karma`](#5-karma--side-effect-ledger) | `@karmic` traces globals/IO/arg-mutations; `KarmicViolation`.     |
| [`examine`](#6-examine--three-marks-introspection) | `examine(obj)` — three orthogonal views of any Python object.     |
| [`buddhism.path`](#7-buddhismpath--project-quality-checker) | CLI: 8 quality checks against a target package.                   |
| [`koans`](#8-koans--guided-tutorial)    | Seven runnable lessons pairing each module with a Python internal. |

---

## 1. `anitya` — decay containers and validity windows

Time as a first-class primitive. Three tools.

**`DecayDict` / `DecaySet`** — *staleness as a continuous gradient*, not a
binary alive/dead flag:

```python
from buddhism import DecayDict

cache: DecayDict[str, dict] = DecayDict(half_life=60.0)
cache.set("user:42", {"name": "Alice"})
value, confidence = cache.get("user:42")
# After 60s, confidence == 0.5; after 120s, 0.25; eventually evicted.
```

**`@impermanent(validity)`** — declare a function whose return value has
a validity window. Past the window, you get back a `Stale[T]` that
demands an explicit decision:

```python
from buddhism import impermanent, Stale, StalenessError

@impermanent(validity=30.0)
def fetch_rate() -> float:
    return external_api.get_rate()

result = fetch_rate()
# Inside 30s: returns float directly.
# After 30s:
match result:
    case Stale(): result = result.refresh()   # re-call
    # or:
    # result = result.accept_stale()           # explicit acknowledgement
    # or just bare access — that raises StalenessError, by design.
```

**`MemoryPressureRegistry`** — drop-on-load registry built on
`weakref.finalize`, releasing in priority order under memory pressure.

---

## 2. `anatta` — structural identity tools

```python
from buddhism import StructuralEq, without_self, diff

# Value semantics on demand
class Point(StructuralEq):
    def __init__(self, x, y):
        self.x = x; self.y = y

Point(1, 2) == Point(1, 2)        # True (same configuration)
Point(1, 2) is Point(1, 2)        # False (distinct objects)
{Point(1, 2), Point(1, 2)}        # set of size 1

# Methods as pure functions over an explicit state
class Counter:
    def step(self, k): return self.n + k

pure_step = without_self(Counter.step)
pure_step({"n": 10}, 5)           # 15 — no instance needed

# A diff that distinguishes "mutated" from "replaced"
d = diff(a, b)
d.same_identity        # a is b
d.same_configuration   # public attrs equal
d.field_changes        # {name: (a_value, b_value)}
d.summary()            # 'mutated: same object, 2 field(s) changed'
```

---

## 3. `karma` — side-effect ledger

```python
from buddhism import karmic, KarmicViolation

@karmic
def update_record(record, value):
    record["v"] = value
    return record["v"]

result, ledger = update_record({"v": 0}, 7)
ledger.arg_mutations   # {0: ({'v': 0}, {'v': 7})}
ledger.is_pure()       # False
```

The ledger names every observed side effect: globals **read**, globals
**written**, **I/O events** (file open / socket connect / subprocess),
arguments **mutated** by reference. Read-tracking is best-effort
(CPython 3.11+ inline-caches LOAD_GLOBAL); write-tracking is reliable.

**Strict mode** turns the ledger into a contract:

```python
@karmic(allow={"global:cache"})
def lookup(key):
    if key in cache: return cache[key]   # OK
    cache[key] = fetch(key)               # OK (allow-listed)
    return cache[key]

@karmic(allow=set())
def vow_of_purity(x):
    return x * 2          # OK
    # any global write or I/O event raises KarmicViolation
```

**Debt** lets test suites assert maximum unacknowledged side-effect
budgets across a suite of calls.

---

## 4. `pratitya` — reactive dependency graph

Two surfaces.

**Standalone signals:**

```python
from buddhism import Cell, derive

a = Cell(1)
b = Cell(2)
c = derive(lambda: a() + b())     # auto-tracks dependence on a, b
c()                                # 3
a.set(10);  c()                    # 12
```

**Class-attribute descriptors (the spreadsheet form):**

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

The deep features:

* **Auto-tracking** via `ContextVar` records edges as a function reads
  its inputs; the dependency set is rebuilt on each recomputation, so
  conditional branches don't accumulate dead edges.
* **Pull-based** evaluation with eager subscribers (`on_change`) only
  if you ask for them.
* **Non-clinging by construction**: edges from `Cell` to its dependents
  live in a `WeakSet` — a `Derived` becoming unreachable is collected
  and silently disappears from the graph.
* **`with batch():`** coalesces multiple writes; each subscriber fires
  at most once, with the correct *before* and *after* values, after
  the cascade completes.
* **`SamsaraError`** on circular dependencies (A → B → A has no still
  point at which to assign a value).
* **`equality_check`** parameter lets you opt into identity-only
  comparison for objects with expensive or side-effectful `__eq__`.
* **`__slots__`-only classes** are supported (declare `__buddhism_nodes__`
  in `__slots__`); a class that is not weak-referenceable must explicitly
  opt into strong-ref mode via `__buddhism_strong_refs__ = True`.

---

## 5. `dukkha` — retention profiler

In Python, *clinging* is the technical name for: reference cycles you
didn't mean to create, caches that keep growing, closures that capture
more than they should, and listeners that outlive their listened-to.
The garbage collector is willing to let go; we are the ones holding on.

```python
from buddhism import observe, let_go, find_cycles, retention_path

# observe() — diff live objects across a block
with observe() as report:
    do_some_work()
print(report.text_report())

# @let_go — assert a function does not retain its inputs (transitive
# retention through the *return value* is fine; named arguments can
# be allow-listed for constructors that legitimately keep inputs)
@let_go(allow={"config"})
def __init__(self, config, *, debug=False):
    self.config = config

# find_cycles — strongly-connected components in your candidate set
cycles = find_cycles([a, b, c])

# retention_path — one path of clinging, root → object
path = retention_path(att.get())
print(path.format())
```

The cross-module bridge: `RetentionReport.pratitya_breakdown()` summarises
*reactive-graph nodes* among the retained objects, so a leaking dependency
graph reports its shape, not just its count.

---

## 6. `examine` — Three Marks introspection

A single function that returns three orthogonal views of any object:

```python
from buddhism import examine

class Sheet(Conditioned):
    a = cell(1)

    @derived
    def b(self): return self.a * 2

s = Sheet()
print(examine(s).text_report())
# examine(<__main__.Sheet object at 0x…>)
#
#   Anitya — change over time:
#     (no time-relevant decoration found)
#
#   Dukkha — what is clinging:
#     alive:                 True
#     direct referrers:      1
#     referrer types:        dict
#     reactive subscribers:  0
#
#   Anatta — configuration of conditions:
#     type:                  Sheet
#     public attrs (3):      ['a', 'b', '__buddhism_nodes__']
#     reactive dependencies: ['a', 'b']
#     pure form:             available via without_self()
```

The output is *progressively richer* as the object adopts more of the
package's primitives.

---

## 7. `buddhism.path` — project-quality checker

A CLI that audits a target package against eight checks:

```bash
$ python -m buddhism.path
buddhism path examined .../src/buddhism

  ✓ Right View            type coverage 92% (threshold 80%)
  ✓ Right Intention       81/81 public functions documented
  ✓ Right Speech          no print() calls in library code
  ✓ Right Action          no unmarked argument mutations
  ✓ Right Livelihood      pure modules touched no I/O
  ✓ Right Effort          test-file ratio 50% (8 tests / 16 src; threshold 50%)
  ✓ Right Mindfulness     30/30 module-level public functions decorated
  ✓ Right Concentration   max complexity 25

  8/8 path factors satisfied. The path is complete.
```

Each check is concretely engineering:

| Step                      | Check                                              |
|---------------------------|---------------------------------------------------|
| Right View                | type-annotation density above threshold            |
| Right Intention           | every public function carries a docstring          |
| Right Speech              | no `print()` in library code                       |
| Right Action              | no unmarked argument mutation                      |
| Right Livelihood          | no I/O in modules declaring `__pure__ = True`      |
| Right Effort              | test coverage threshold                            |
| Right Mindfulness         | every public function tagged with an effect-decorator |
| Right Concentration       | cyclomatic complexity below threshold              |

Configurable via `[tool.buddhism.path]` in `pyproject.toml`. Output
in JSON via `--json` for CI. The package eats its own dog food.

---

## 8. `koans` — guided tutorial

Seven runnable lessons pairing each Buddhist concept with one deep
Python feature:

```bash
python -m buddhism.koans
# ✓ k01_impermanence       mutation, aliasing, default-arg trap
# ✓ k02_dependent_origination  descriptors + reactive graph
# ✓ k03_non_self            identity, equality, __dict__
# ✓ k04_clinging            weakref, gc, retention
# ✓ k05_emptiness           None, sentinels, falsy values
# ✓ k06_karma               globals tracking, I/O patches, snapshots
# ✓ k07_three_marks         examine() across all primitives
#
# All koans completed.
```

Passing by default — they're a guided tour. To turn them into self-tests,
replace any literal answer with `__` (imported from `buddhism.koans`)
and re-run; the runner stops at the first failure with the koan's hint.

---

## Examples

```bash
python examples/reactive_spreadsheet.py     # cascading recompute
python examples/reactive_config.py          # config whose derivations re-arise
python examples/leak_detection.py           # observe(), @let_go, find_cycles
```

---

## Doctrinal mapping (the design philosophy)

| Doctrine                      | Engineering primitive                         | Module               |
|-------------------------------|-----------------------------------------------|----------------------|
| **Pratītyasamutpāda** (dependent origination) | reactive dependency graph                  | `pratitya`           |
| **Dukkha** (clinging)         | retention profiler                            | `dukkha`             |
| **Anitya** (impermanence)     | decay containers, validity windows            | `anitya`             |
| **Anatta** (non-self)         | structural identity, pure-form transformation | `anatta`             |
| **Karma**                     | side-effect ledger                            | `karma`              |
| **Three Marks**               | runtime introspection across all three        | `examine`            |
| **Eightfold Path**            | project-quality discipline                    | `buddhism.path`      |

Each row is a one-to-one mapping. No module is a renamed standard utility;
each one uses Python's deepest leverage points (descriptors, `gc`,
`weakref`, `ContextVar`, AST analysis, runtime patching). If you couldn't
justify the entry as engineering, it didn't ship.

The point of the package is that *the labels are the most economical way
of naming the design*, not a layer of paint. Two thousand five hundred
years ago, four contemplatives looked carefully at how things actually
work, and most of what they noticed has direct, useful Python analogues.
This package takes those analogues seriously enough to write them down.

---

## Design principles

1. **Doctrinal, not decorative.** Every Buddhist term in the public API
   maps to a real Python primitive. If we couldn't justify it as engineering,
   we didn't ship it.
2. **Non-clinging by default.** The library uses `WeakSet` and `weakref`
   throughout so its own data structures don't become a source of dukkha.
3. **Pure-Python, no dependencies.** Same behaviour on CPython 3.9+ on
   every platform.
4. **Eats its own dog food.** `python -m buddhism.path` returns 8/8 on
   `buddhism` itself.

---

## Contributing

PRs welcome. Especially:

* additional koans (one new Buddhist concept paired with one deep Python feature)
* corner-case tests for the reactive graph (cycles, threading, asyncio)
* visualisation of retention graphs in `dukkha`
* a real `coverage` integration in `buddhism.path`'s Right Effort check

---

## License

MIT — see [LICENSE](LICENSE).

---

> *"Whatever has the nature of arising, all that has the nature of cessation."*
>                                          — Aññāsi-Koṇḍañña, on the first sermon
