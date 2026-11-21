"""Simulator regression tests, driven by a simulated clock (fast, deterministic per seed).

Regression for the stall found in the first handover: the robot pinned itself
against an obstacle corner, nav stayed EXECUTING forever and distance froze.
"""
import pytest

from lite3_bridge.config import load_config
from lite3_bridge.sim import INFLATE, OCC, FREE, H, W, SimSource, w2c
from lite3_bridge.state import TelemetryStore


def make_sim(seed, faults=False):
    cfg = load_config()
    cfg["sim"]["seed"] = seed
    cfg["sim"]["topic_faults"] = faults
    src = SimSource(TelemetryStore(cfg, "sim"), cfg)
    src._register()  # no background thread; the test drives tick()
    return src


def run(src, seconds, now=1000.0, stop_when_complete=False):
    for _ in range(int(seconds / src.DT)):
        now += src.DT
        src.tick(now)
        if stop_when_complete and src.complete_at is not None:
            break
    return now


def body_reachable_coverage(src):
    """Fraction of cells the robot body can reach (outside the wall margin) that are explored."""
    truth, known = src.world.truth, src.explorer.known

    def near_wall(x, y):
        for j in range(-INFLATE, INFLATE + 1):
            for i in range(-INFLATE, INFLATE + 1):
                if i * i + j * j <= INFLATE * INFLATE and 0 <= x + i < W and 0 <= y + j < H \
                        and truth[(y + j) * W + x + i] == OCC:
                    return True
        return False

    start = w2c(0.0, 0.0)
    seen, stack = {start}, [start]
    while stack:
        x, y = stack.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in seen and not near_wall(*n):
                seen.add(n)
                stack.append(n)
    return sum(1 for x, y in seen if known[y * W + x] == FREE) / len(seen)


@pytest.mark.parametrize("seed", [7, 9, 10])
def test_sim_keeps_moving(seed):
    src = make_sim(seed)
    run(src, 120)
    assert src.travelled > 15.0, f"seed {seed}: robot stalled after {src.travelled:.1f} m"


@pytest.mark.parametrize("seed", [7, 8, 9, 11])
def test_sim_explores_everything_reachable(seed):
    src = make_sim(seed)
    run(src, 400, stop_when_complete=True)
    assert src.complete_at is not None, f"seed {seed}: exploration never completed"
    assert body_reachable_coverage(src) > 0.95


def test_injected_stall_is_not_hidden_by_recovery():
    """The 'stuck' fault must stay visible as a stall: the progress watchdog must not abort it."""
    src = make_sim(7)
    now = run(src, 15)
    assert src.goal is not None
    src.fault = ("stuck", now + 12.0)
    x0, y0 = src.x, src.y
    statuses = set()
    for _ in range(int(10 / src.DT)):
        now += src.DT
        src.tick(now)
        statuses.add(src.store.nav_status["status"])
    # goal stays active (never aborted by the watchdog) and the robot does not move,
    # so the dashboard's STALLED detection sees exactly what a real stall looks like
    assert statuses == {"EXECUTING"}
    assert abs(src.x - x0) + abs(src.y - y0) < 0.1
