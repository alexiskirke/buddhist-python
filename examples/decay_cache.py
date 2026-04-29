"""Confidence-graded cache: every read returns ``(value, confidence)``.

A common LLM-agent pattern: you cached a fact 30 seconds ago. Should you
trust it? With a TTL you'd get only "yes" or "no". With a half-life
you get a continuous gradient that you can route on.

Run::

    python examples/decay_cache.py
"""

from __future__ import annotations

from buddhism import DecayDict, DecaySet


def main() -> None:
    # A cache where the *belief* in a value decays smoothly.
    rates: DecayDict[str, float] = DecayDict(half_life=2.0)

    rates.set("USDGBP", 0.79)
    rates.set("USDEUR", 0.91)

    print("Just inserted:")
    for k, v, c in rates.items():
        print(f"  {k}={v:.4f}  confidence={c:.2f}")

    import time
    time.sleep(2.0)

    print("\nAfter one half-life:")
    for k, v, c in rates.items():
        print(f"  {k}={v:.4f}  confidence={c:.2f}")

    # DecaySet: like DecayDict but with True as the value.
    seen: DecaySet[str] = DecaySet(half_life=1.0)
    seen.add("user_42")
    print(f"\n'user_42' in seen: {'user_42' in seen}  conf={seen.confidence('user_42'):.2f}")
    time.sleep(2.0)
    print(f"'user_42' in seen: {'user_42' in seen}  conf={seen.confidence('user_42'):.2f}")


if __name__ == "__main__":
    main()
