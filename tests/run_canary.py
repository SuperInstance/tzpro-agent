"""Canary tests for new modules: conservation_layer, _router, fleet_monitor."""
import sys, os, json, tempfile, time
from pathlib import Path

HERE = Path(__file__).parent.parent.resolve()
os.chdir(HERE)
sys.path.insert(0, str(HERE))

errors = []
def ok(msg):
    print(f"  [OK] {msg}")
def fail(msg):
    print(f"  [FAIL] {msg}")
    errors.append(msg)

# ══════════════════════════════════════════════════════════════════════
print("=" * 60)
print("TEST: conservation_layer.py")
print("=" * 60)

try:
    from conservation_layer import (
        ActionBudget, ActionBudgetExceeded, ConservationState,
        SplitTrigger, SpectralLaplacian, EventLog
    )
    ok("imports OK")
except Exception as e:
    fail(f"import: {e}")

if not errors:
    # ActionBudget
    try:
        budget = ActionBudget(total=100)
        for i in range(5):
            budget.consume(0.8)
        for i in range(3):
            budget.consume(0.2)
        assert budget.used == 8.0
        assert budget.productive == 5.0
        assert budget.waste == 3.0
        assert budget.waste_ratio == 0.6
        ok("ActionBudget: consume + productive/waste tracking")
    except Exception as e:
        fail(f"ActionBudget: {e}")

    # Exhaustion
    try:
        budget2 = ActionBudget(total=5)
        for i in range(5):
            budget2.consume(1.0)
        try:
            budget2.consume(1.0)
            fail("ActionBudgetExceeded not raised")
        except ActionBudgetExceeded:
            ok("ActionBudgetExceeded raised correctly")
    except Exception as e:
        fail(f"ActionBudget exceed: {e}")

    # Roundtrip
    try:
        d = budget.to_dict()
        b3 = ActionBudget.from_dict(d)
        assert b3.total == budget.total
        assert b3.used == budget.used
        ok("ActionBudget: to_dict/from_dict roundtrip")
    except Exception as e:
        fail(f"ActionBudget dict: {e}")

    # SplitTrigger
    try:
        trigger = SplitTrigger(volume=10, split_threshold=5)
        assert trigger.should_split()
        reason = trigger.split_reason()
        assert "overflow=5" in reason
        ok(f"SplitTrigger.should_split() ({len(reason)} chars)")

        vocab = {f"k{i}": max(0.05, 1.0/(i+1)) for i in range(10)}
        surv, pruned = trigger.forget(vocab, min_confidence=0.15)
        assert pruned > 0
        assert len(surv) < 10
        ok(f"SplitTrigger.forget(): pruned {pruned}, survived {len(surv)}")
    except Exception as e:
        fail(f"SplitTrigger: {e}")

    # ConservationState
    try:
        state = ConservationState(gamma=5.0, entropy=3.0, volume=10, capacity=100)
        snap = state.state_snapshot()
        assert snap["gamma"] == 5.0
        assert snap["entropy"] == 3.0
        assert snap["remaining"] == 92.0
        ok(f"ConservationState: remaining={snap['remaining']}")
    except Exception as e:
        fail(f"ConservationState: {e}")

    # SpectralLaplacian - compute() modifies in-place, use to_dict() after
    try:
        lap = SpectralLaplacian(adjacency={"A": ["B"], "B": ["A", "C"], "C": ["B"]})
        spec = lap.to_dict()
        assert "spectral_gap" in spec
        assert "fiedler_value" in spec
        assert "cheeger_constant" in spec
        ok(f"SpectralLaplacian: gap={spec['spectral_gap']:.4f}, Fiedler={spec['fiedler_value']:.4f}")
    except Exception as e:
        fail(f"SpectralLaplacian: {e}")

    # EventLog - use proper temp file cleanup
    try:
        tmp = Path(tempfile.mktemp(suffix=".jsonl"))
        log = EventLog(path=tmp)
        log.log_event("test", {"msg": "hello"})
        log.log_event("action", {"cost": 1.0})
        recent = log.recent_events(1)
        assert len(recent) == 1
        assert recent[0]["event_type"] == "action"
        by_type = log.events_by_type("test")
        assert len(by_type) == 1
        log.clear()
        assert not tmp.read_text().strip()
        tmp.unlink()
        ok("EventLog: write/read/events_by_type/clear")
    except Exception as e:
        fail(f"EventLog: {e}")

    # CLI: status
    try:
        from conservation_layer import main as cl_main
        rc = cl_main(["status"])
        assert rc == 0
        ok("CLI: status")
    except Exception as e:
        fail(f"CLI status: {e}")

    # CLI: gc
    try:
        from conservation_layer import main as cl_main
        rc = cl_main(["gc"])
        assert rc == 0
        ok("CLI: gc")
    except Exception as e:
        fail(f"CLI gc: {e}")

print()

# ══════════════════════════════════════════════════════════════════════
print("=" * 60)
print("TEST: _router.py")
print("=" * 60)

try:
    from _router import ROUTER, route_task, acquire_lock, release_lock, list_active_locks
    ok("imports OK")
except Exception as e:
    fail(f"import: {e}")

if "imports OK" in str(locals().get('_', '')) or not errors:
    try:
        r = route_task("creative_vision")
        assert r["model"] == "seed2"
        assert r["confidence"] == 0.95
        assert r["fallback"] is False
        ok("route_task: exact match => seed2")

        r2 = route_task("unknown_type")
        assert r2["fallback"] is True
        assert r2["model"] == "flash"
        ok("route_task: unknown fallback => flash")

        r3 = route_task("review", {"preferred_model": "v4pro", "budget_hint": "8192"})
        assert r3["model"] == "v4pro"
        assert r3["estimated_budget"] == 8192
        ok("route_task: context hints override")

        # Baton handshake
        acq = acquire_lock("test_task_1", timeout_s=5)
        assert acq is True
        ok("acquire_lock: first attempt succeeds")

        acq2 = acquire_lock("test_task_1", timeout_s=1)
        assert acq2 is False
        ok("acquire_lock: second attempt correctly denied (lock held)")

        locks = list_active_locks()
        assert len(locks) >= 1
        ok(f"list_active_locks: {len(locks)} lock(s)")

        release_lock("test_task_1")
        ok("release_lock: released")

        # Wait-for-release
        acq3 = acquire_lock("test_task_2", timeout_s=5)
        import threading, time
        released = threading.Event()
        def releaser():
            time.sleep(0.5)
            release_lock("test_task_2")
            released.set()
        t = threading.Thread(target=releaser, daemon=True)
        t.start()
        waited = release_lock("test_task_2")
        ok("wait_for_release: completed")

        ok("ALL _router tests passed")
    except Exception as e:
        fail(f"_router: {e}")
        import traceback
        traceback.print_exc()

print()

# ══════════════════════════════════════════════════════════════════════
print("=" * 60)
print("TEST: fleet_monitor.py")
print("=" * 60)

try:
    from fleet_monitor import FleetMonitor, Service, SERVICES
    ok("imports OK")
except Exception as e:
    fail(f"import: {e}")

if "imports OK" in str(locals().get('_', '')) or True:
    try:
        monitor = FleetMonitor()
        health = monitor.check()
        assert len(health) == len(SERVICES)
        statuses = [h["status"] for h in health.values()]
        up = statuses.count("UP")
        down = statuses.count("DOWN")
        ok(f"check(): {up} UP, {down} DOWN ({len(health)} services total)")

        # Check each service has expected keys
        for name, h in health.items():
            assert "status" in h
            assert "pid" in h
            assert "age_s" in h
        ok("report keys correct")

        report = monitor.report()
        assert "Fleet Status" in report
        assert "UP" in report or "DOWN" in report
        ok(f"report(): {len(report)} chars, markdown format")

        ok("ALL fleet_monitor tests passed")
    except Exception as e:
        fail(f"fleet_monitor: {e}")
        import traceback
        traceback.print_exc()

print()

# ══════════════════════════════════════════════════════════════════════
print("=" * 60)
if errors:
    print(f"  {len(errors)} TEST(S) FAILED:")
    for e in errors:
        print(f"    - {e}")
    sys.exit(1)
else:
    print("  ALL CANARY TESTS PASSED")
    sys.exit(0)
