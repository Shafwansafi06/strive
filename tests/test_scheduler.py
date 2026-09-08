"""SCH-01/02/03 acceptance: cadence config, BranchState, multi-rate scheduling."""
import threading
import pytest
from strive.branches import BranchResult, weight_mask
from strive.scheduler import (DEFAULT_CADENCE_MS, BranchState, MultiRateScheduler)


def ok(name, score=.4):
    return BranchResult(name=name, score=score, confidence=.9, available=True)


# ------------------------------------------------------------ SCH-01 cadence

def test_default_cadence_matches_the_ticket():
    assert DEFAULT_CADENCE_MS == {"channel": 500, "prosody": 500, "artifact": 1000,
                                  "session": 2000, "identity": 3000, "fusion": 500}


def test_cadence_is_config_driven():
    scheduler = MultiRateScheduler({"artifact": 250})
    assert scheduler.cadence["artifact"] == 250
    assert scheduler.cadence["session"] == 2000     # untouched defaults survive


@pytest.mark.parametrize("bad", [0, -100, "fast", None])
def test_invalid_cadence_rejected(bad):
    with pytest.raises(ValueError):
        MultiRateScheduler({"artifact": bad})


# --------------------------------------------------------- SCH-02 BranchState

def test_missing_and_stale_are_distinct_states():
    state = BranchState(stale_after_ms=1000)
    assert state.is_missing() and not state.is_stale(now=0)
    assert state.usable(now=0) is None
    assert state.age_ms(now=0) is None

    state.result, state.updated_at = ok("artifact"), 100.
    assert not state.is_missing()
    assert not state.is_stale(now=100.5)          # 500 ms old, limit 1000 ms
    assert state.usable(now=100.5) is not None
    assert state.is_stale(now=102.)               # 2000 ms old
    assert state.usable(now=102.) is None
    assert state.age_ms(now=102.) == 2000.


def test_stale_window_defaults_to_three_cadences():
    scheduler = MultiRateScheduler()
    assert scheduler.states["artifact"].stale_after_ms == 3000
    assert scheduler.states["session"].stale_after_ms == 6000


def test_snapshot_marks_missing_and_stale_explicitly():
    scheduler = MultiRateScheduler({"artifact": 1000})
    snapshot = scheduler.snapshot(now=0)
    assert snapshot["artifact"].available is False
    assert snapshot["artifact"].score is None      # never a zero
    assert "BRANCH_NOT_YET_RUN" in snapshot["artifact"].reason_codes

    scheduler.publish("artifact", ok("artifact"), now=0)
    assert scheduler.snapshot(now=1)["artifact"].available is True

    stale = scheduler.snapshot(now=10)["artifact"]
    assert stale.available is False and stale.score is None
    assert "BRANCH_STALE" in stale.reason_codes
    assert stale.metadata["age_ms"] == 10000.


# ----------------------------------------------------- SCH-03 multi-rate runs

def test_due_respects_cadence():
    scheduler = MultiRateScheduler({"artifact": 1000})
    assert scheduler.due("artifact", now=0)        # never run yet
    scheduler.begin("artifact", now=0)
    assert not scheduler.due("artifact", now=0.5)  # 500 ms later, cadence 1000
    assert scheduler.due("artifact", now=1.0)      # exactly at cadence


def test_fusion_updates_every_hop_while_artifact_does_not():
    """The core SCH-03 requirement at a 0.5 s hop."""
    scheduler = MultiRateScheduler()               # fusion 500 ms, artifact 1000 ms
    fusion_runs = artifact_runs = 0
    for step in range(8):                          # 8 hops of 0.5 s = 4 s
        now = step * 0.5
        if scheduler.due("fusion", now):
            scheduler.begin("fusion", now)
            fusion_runs += 1
        if scheduler.due("artifact", now):
            scheduler.begin("artifact", now)
            scheduler.publish("artifact", ok("artifact"), now)
            artifact_runs += 1
        else:
            scheduler.skip("artifact")
    assert fusion_runs == 8                        # every hop
    assert artifact_runs == 4                      # every other hop
    assert scheduler.states["artifact"].skips == 4


def test_skipped_branch_still_contributes_its_cached_result():
    scheduler = MultiRateScheduler({"artifact": 1000})
    scheduler.begin("artifact", now=0)
    scheduler.publish("artifact", ok("artifact", .8), now=0)
    # 0.5 s later the branch is not due, but its recent result is still usable.
    assert not scheduler.due("artifact", now=0.5)
    reused = scheduler.snapshot(now=0.5)["artifact"]
    assert reused.available and reused.score == .8


def test_unregistered_branch_is_never_throttled():
    assert MultiRateScheduler().due("brand_new", now=0)


def test_branch_failure_does_not_raise_and_masks_the_branch():
    """SCH-03: a branch exception must not kill the call session."""
    scheduler = MultiRateScheduler()
    scheduler.fail("artifact", "MODEL_OR_INDEX_ERROR")
    result = scheduler.snapshot()["artifact"]
    assert result.available is False and result.score is None
    assert "MODEL_OR_INDEX_ERROR" in result.reason_codes
    # Other branches keep working.
    scheduler.publish("session", ok("session"))
    assert scheduler.snapshot()["session"].available is True


def test_telemetry_exposes_queue_delay_and_counters():
    scheduler = MultiRateScheduler()
    scheduler.record_queue_delay(12.5)
    scheduler.begin("artifact", now=0)
    scheduler.publish("artifact", ok("artifact"), now=0)
    scheduler.skip("artifact")
    scheduler.fail("session", "COLD_START")

    telemetry = scheduler.telemetry(now=0.1)
    assert telemetry["queue_delay_ms"] == 12.5
    assert telemetry["cadence_ms"]["artifact"] == 1000
    assert telemetry["branches"]["artifact"]["runs"] == 1
    assert telemetry["branches"]["artifact"]["skips"] == 1
    assert telemetry["branches"]["session"]["failures"] == 1
    assert telemetry["branches"]["identity"]["missing"] is True


def test_negative_queue_delay_is_clamped():
    scheduler = MultiRateScheduler()
    scheduler.record_queue_delay(-5)
    assert scheduler.telemetry()["queue_delay_ms"] == 0.


def test_reset_drops_cached_results():
    scheduler = MultiRateScheduler()
    scheduler.begin("artifact", now=0)
    scheduler.publish("artifact", ok("artifact"), now=0)
    scheduler.reset()
    assert scheduler.snapshot()["artifact"].available is False
    assert scheduler.due("artifact", now=0)


def test_scheduler_is_thread_safe():
    scheduler = MultiRateScheduler()
    errors = []

    def hammer(index):
        try:
            for _ in range(200):
                scheduler.due("artifact")
                scheduler.begin("artifact")
                scheduler.publish("artifact", ok("artifact"))
                scheduler.snapshot()
                scheduler.telemetry()
        except Exception as e:  # pragma: no cover - only on a real race
            errors.append(e)

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert scheduler.states["artifact"].runs == 1200


# ------------------------------------------- BR-01 masking over scheduler output

def test_fusion_masks_stale_and_missing_branches():
    scheduler = MultiRateScheduler()
    scheduler.publish("artifact", ok("artifact", .6), now=0)
    scheduler.publish("session", ok("session", .2), now=0)
    weights = {"artifact": .5, "session": .3, "identity": .2}

    fresh = weight_mask(scheduler.snapshot(now=0.1), weights)
    assert set(fresh) == {"artifact", "session"}          # identity never ran
    assert sum(fresh.values()) == pytest.approx(1.0)

    # Once artifact expires, weight redistributes rather than counting zero.
    late = weight_mask(scheduler.snapshot(now=20), weights)
    assert late == {}                                      # everything expired


# ------------------------------------------ SCH-03 end-to-end through the engine

def test_multi_rate_halves_artifact_work_but_not_the_event_rate(index):
    """A 0.5 s hop with a 1000 ms artifact cadence: every hop emits, half compute."""
    from strive.audio import RATE
    from strive.config import Settings
    from strive.demo import scenario_audio
    from strive.engine import Call
    from strive.features import DSPExtractor

    audio = scenario_audio("steady", 20)

    def run(multi_rate):
        call = Call(Settings(window_s=2.0, stride_s=0.5, multi_rate=multi_rate,
                             branch_cadence_ms={"artifact": 1000}), DSPExtractor(), index)
        events = []
        for i, start in enumerate(range(0, len(audio), RATE)):
            events.extend(call.feed(audio[start:start + RATE], i))
        call.close()
        return events

    every, throttled = run(False), run(True)

    # Fusion still refreshes on every hop in both modes.
    assert len(every) == len(throttled) == 37

    # But the artifact branch actually ran half as often.
    ran = [e for e in throttled if e["stage_ms"].get("artifact", 0) > 0]
    reused = [e for e in throttled if "BRANCH_RESULT_REUSED" in e["reasons"]]
    assert len(ran) < len(throttled)
    assert reused, "throttled windows must reuse the cached branch result"
    assert len(ran) + len(reused) == len(throttled)

    # Reused windows still carry a usable risk score, not a hole.
    scored = [e for e in reused if e["s_risk"] is not None]
    assert scored, "reused evidence must still produce a risk value"

    # Total artifact compute is meaningfully lower.
    def artifact_ms(events):
        return sum(e["stage_ms"].get("artifact", 0.) for e in events)
    assert artifact_ms(throttled) < artifact_ms(every) * .75


def test_scheduler_telemetry_reaches_the_event(index):
    from strive.audio import RATE
    from strive.config import Settings
    from strive.demo import scenario_audio
    from strive.engine import Call
    from strive.features import DSPExtractor

    call = Call(Settings(window_s=2.0, stride_s=0.5, multi_rate=True), DSPExtractor(), index)
    audio = scenario_audio("steady", 8)
    events = []
    for i, start in enumerate(range(0, len(audio), RATE)):
        events.extend(call.feed(audio[start:start + RATE], i))
    call.close()

    telemetry = events[-1]["scheduler"]
    assert "queue_delay_ms" in telemetry
    assert telemetry["cadence_ms"]["artifact"] == 1000
    assert telemetry["branches"]["artifact"]["runs"] >= 1
    assert telemetry["branches"]["artifact"]["skips"] >= 1


def test_default_config_is_unchanged_by_the_scheduler(index):
    """multi_rate defaults off: identical scores to the pre-scheduler engine."""
    from strive.audio import RATE
    from strive.config import Settings
    from strive.demo import scenario_audio
    from strive.engine import Call
    from strive.features import DSPExtractor

    assert Settings().multi_rate is False
    call = Call(Settings(), DSPExtractor(), index)
    audio = scenario_audio("switch", 24)
    events = []
    for i, start in enumerate(range(0, len(audio), RATE)):
        events.extend(call.feed(audio[start:start + RATE], i))
    call.close()
    assert not any("BRANCH_RESULT_REUSED" in e["reasons"] for e in events)
