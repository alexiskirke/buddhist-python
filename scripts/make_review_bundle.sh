#!/usr/bin/env bash
# Assemble a single Markdown review bundle of the package's "thesis" surfaces:
# README, directory tree, the two flagship modules, the package __init__,
# two illustrative koans, and the test suites for both flagships.
#
# Output: REVIEW_BUNDLE.md  (paste this into any AI for an honest review.)

set -euo pipefail
cd "$(dirname "$0")/.."

OUT="REVIEW_BUNDLE.md"

emit_file() {
    local path="$1"
    local lang="${2:-}"
    {
        printf '\n## `%s`\n\n' "$path"
        printf '```%s\n' "$lang"
        cat "$path"
        printf '```\n'
    } >> "$OUT"
}

cat > "$OUT" <<'EOF'
# buddhist-python — review bundle

Public repo (verified anonymously reachable):
**https://github.com/alexiskirke/buddhist-python**

This is a single-file dump of the project's load-bearing surfaces so that
any reviewer can give a verdict on **novelty / usefulness** without needing
to fetch anything live.

Thesis (one sentence): *Buddhist concepts as load-bearing Python infrastructure
— a reactive dependency graph (Dependent Origination), a clinging/retention
profiler (Dukkha), and a koans tutorial track that teaches both the
philosophy and the underlying Python internals.*

---

## Directory tree
EOF

{
    printf '\n```\n'
    # Generate a clean tree without venv / git / caches.
    find . -type f \
        \( -name "*.py" -o -name "*.toml" -o -name "*.md" -o -name "*.yml" \
           -o -name "LICENSE" -o -name "py.typed" -o -name "*.sh" \) \
        -not -path "./venv/*" \
        -not -path "./.git/*" \
        -not -path "./build/*" \
        -not -path "*.egg-info/*" \
        -not -path "./.pytest_cache/*" \
        -not -path "*/__pycache__/*" \
        -not -path "./REVIEW_BUNDLE.md" \
        | sort | sed 's|^\./||'
    printf '```\n'
} >> "$OUT"

# Project metadata
emit_file pyproject.toml toml
emit_file README.md markdown

# Package surface
emit_file src/buddhism/__init__.py python

# The seven modules
emit_file src/buddhism/pratitya.py python
emit_file src/buddhism/dukkha.py python
emit_file src/buddhism/anitya.py python
emit_file src/buddhism/anatta.py python
emit_file src/buddhism/karma.py python
emit_file src/buddhism/examine.py python
emit_file src/buddhism/path/__init__.py python
emit_file src/buddhism/path/checks.py python
emit_file src/buddhism/path/cli.py python

# Koans surface
emit_file src/buddhism/koans/__init__.py python
emit_file src/buddhism/koans/_runner.py python
emit_file src/buddhism/koans/k02_dependent_origination.py python
emit_file src/buddhism/koans/k04_clinging.py python
emit_file src/buddhism/koans/k06_karma.py python
emit_file src/buddhism/koans/k07_three_marks.py python

# Examples (one per module)
emit_file examples/reactive_spreadsheet.py python
emit_file examples/leak_detection.py python
emit_file examples/decay_cache.py python
emit_file examples/structural_identity.py python
emit_file examples/karma_audit.py python
emit_file examples/three_marks.py python

# Tests
emit_file tests/test_pratitya.py python
emit_file tests/test_dukkha.py python
emit_file tests/test_anitya.py python
emit_file tests/test_anatta.py python
emit_file tests/test_karma.py python
emit_file tests/test_examine.py python
emit_file tests/test_path.py python
emit_file tests/test_integration.py python

cat >> "$OUT" <<'EOF'

---

## Reviewer instructions

Please answer:

1. **Novelty.** Is the mapping doctrine → Python primitive (Dependent
   Origination → reactive descriptor graph; Dukkha → gc/weakref retention
   profiler; Anatta → identity/equality lessons; Anitya → roadmap) *load-bearing*,
   or is it cosmetic naming over standard tooling?
2. **Usefulness.** Setting aside the philosophy framing, are any of these
   modules independently useful as Python tooling? (i.e. would a working
   Python developer reach for them in a real project?)
3. **Quality.** Spot any correctness or design issues in `pratitya.py`,
   `dukkha.py`, or the descriptor surface. Pay particular attention to:
   the WeakSet-of-dependents non-clinging invariant, the implicit-batch
   inside `Cell.set`, the cycle detection (Tarjan SCC with transparent-
   container expansion), and the `@let_go` retention-detection heuristic.
4. **Virality vector.** Is the koans-as-runnable-tutorial track
   (`python -m buddhism.koans`) a real differentiator?

A direct verdict — "yes, ship it" / "no, here's what's hollow" / "fix
these N things first" — is more useful than diplomatic hedging.
EOF

echo "Wrote $OUT ($(wc -l < "$OUT") lines, $(wc -c < "$OUT") bytes)"
