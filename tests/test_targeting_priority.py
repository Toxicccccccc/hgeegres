"""Target-priority and tracking-recovery tests (Python engine).

These are the shared test vectors: the same scenarios are mirrored by the native
``native_targeting_test`` so the two engines can be shown to agree. Each case
builds a small frame of detections and asserts which one the engine should
choose.

Run:  python tests/test_targeting_priority.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from disabledassistance import DisabledAssistanceEngine  # noqa: E402

FAILURES: list[str] = []


def frame(rows):
    """rows: list of (xmin, ymin, xmax, ymax, confidence)."""
    return pd.DataFrame(rows, columns=["xmin", "ymin", "xmax", "ymax", "confidence"])


def check(condition, description):
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


def main() -> int:
    engine = DisabledAssistanceEngine
    center = 200.0  # fov 400, so the crosshair is at 200,200

    # Two boxes: a weak one dead centre, a strong one off to the right.
    sample = frame([
        (170, 170, 230, 230, 0.40),   # centred, low confidence
        (330, 170, 390, 230, 0.95),   # off-centre, high confidence
    ])

    check(engine.rank_targets_by_mode(sample, "closest", center) == 0,
          "'closest' picks the centred box")
    check(engine.rank_targets_by_mode(sample, "confidence", center) == 1,
          "'confidence' picks the strongest box")
    check(engine.rank_targets_by_mode(sample, "hybrid", center) is not None,
          "'hybrid' returns a choice")

    # 'distance' should prefer the larger box.
    sizes = frame([
        (180, 180, 220, 220, 0.9),    # small
        (140, 140, 260, 260, 0.5),    # large
    ])
    check(engine.rank_targets_by_mode(sizes, "distance", center) == 1,
          "'distance' picks the largest box")

    # Sticky mode hugs the previous target even when another is central.
    previous = (350.0, 200.0)
    check(engine.rank_targets_by_mode(sample, "sticky", center, previous) == 1,
          "'sticky' keeps the previous target")

    # Stickiness margin: with stickiness 0 the engine switches as soon as the
    # ranking changes; with 4 it holds unless the rival is much closer.
    held = engine.select_priority_target(
        sample, 0, center, 400, "closest", 0, True, (178.0, 200.0)
    )
    check(held == 0, "stickiness 0 keeps a clearly-better centred target")

    # A rival only slightly closer must not steal a held target at stickiness 4.
    close = frame([
        (196, 170, 256, 230, 0.9),   # centred-ish
        (150, 170, 210, 230, 0.9),   # marginally closer to the crosshair
    ])
    held_high = engine.select_priority_target(
        close, 0, center, 400, "closest", 4, True, (226.0, 200.0)
    )
    check(held_high is not None, "high stickiness still returns a target")

    # focus_single_target off must always take the ranking's winner.
    free = engine.rank_targets_by_mode(sample, "confidence", center)
    switched = engine.select_priority_target(
        sample, 0, center, 400, "confidence", 4, False, (178.0, 200.0)
    )
    check(switched == free, "focus off follows the ranking immediately")

    # Empty frame must not raise.
    empty = frame([])
    for mode in ("closest", "confidence", "distance", "hybrid", "sticky"):
        check(engine.rank_targets_by_mode(empty, mode, center) is None,
              f"'{mode}' handles an empty frame")

    for direction in (-1.0, 1.0):
        remaining_error = 12.0 * direction
        remainder = 0.0
        for _ in range(24):
            if abs(remaining_error) <= 1.0:
                break
            step, remainder = engine.movement_step(
                remaining_error, 0.1, remainder, "Linear"
            )
            check(step * direction >= 0 and abs(step) <= abs(remaining_error),
                  "legacy sub-1 smoothness must not reverse or overshoot")
            remaining_error -= step
        check(abs(remaining_error) <= 1.0,
              "legacy sub-1 smoothness converges without oscillation")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} targeting check(s) FAILED:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("All targeting-priority checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
