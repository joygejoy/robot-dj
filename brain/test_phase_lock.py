"""Offline unit tests for phase_lock.py - no Mixxx, no OSC, no MIDI, no pytest.

Run it directly:

    python test_phase_lock.py

It prints a "PASS" line for each check, prints "ALL PHASE-LOCK TESTS PASSED" at
the end, and exits 0. On any failure it raises an AssertionError (non-zero exit),
so it works as a plain CI/pre-flight gate without any test framework installed.

WHY A HAND-CONTROLLED CLOCK
---------------------------
PhaseLock never reads the clock itself - every method takes a `now` timestamp
from us. That lets these tests fabricate a perfectly steady 128 bpm track and
feed samples on a fake clock we advance by hand. The results are then fully
deterministic: no sleeping, no real time, no flakiness, and the whole ~10 seconds
of "music" runs instantly.

This file imports ONLY phase_lock and the standard library, proving the core is
testable with zero third-party dependencies.
"""
from phase_lock import PhaseLock, DeckState, format_status


# --- Test fixture: a synthetic, perfectly steady track ----------------------

BPM = 128.0
BEATS_PER_SEC = BPM / 60.0        # 2.1333... beats every second
SAMPLE_HZ = 30.0                  # feed updates 30 times a second (like a UI tick)
DURATION_S = 10.0                 # simulate ten seconds of playback
T0 = 1000.0                       # arbitrary monotonic start; value doesn't matter


def ground_truth_beats(t: float) -> float:
    """The TRUE combined beat number at elapsed-since-start time `t` (seconds).

    For a rock-steady track this is just time * beats-per-second. This is the
    answer PhaseLock is trying to reconstruct from wrapping beat_distance samples.
    """
    return t * BEATS_PER_SEC


def ground_truth_beat_distance(t: float) -> float:
    """The fractional phase (0..1) a real Mixxx would report at elapsed time `t`.

    It ramps up linearly and resets to 0 at every beat line - exactly the
    wrapping signal PhaseLock has to turn back into a monotonic beat count.
    """
    return ground_truth_beats(t) % 1.0


def check(label: str, condition: bool) -> None:
    """Assert `condition`, printing a PASS line or raising with a clear label."""
    if not condition:
        raise AssertionError(f"FAIL: {label}")
    print(f"PASS: {label}")


# --- Tests ------------------------------------------------------------------

def test_tracks_steady_playback():
    """Feed ~10 s of a 128 bpm track at 30 Hz and check the estimate holds up.

    Covers (a) monotonic increase, (b) correct rate, and (c) the ~21.33 total.
    """
    lock = PhaseLock()
    n_samples = int(DURATION_S * SAMPLE_HZ)  # 300 intervals -> 301 samples (i=0..300)

    beats_seen = []
    for i in range(n_samples + 1):
        elapsed = i / SAMPLE_HZ
        now = T0 + elapsed
        lock.update(
            now,
            bpm=BPM,
            beat_distance=ground_truth_beat_distance(elapsed),
            playing=True,
            playposition=elapsed / DURATION_S,
        )
        beats_seen.append(lock.beat_now(now))

    # (a) The estimate must never go backwards while the music plays forward.
    monotonic = all(
        beats_seen[i] < beats_seen[i + 1] for i in range(len(beats_seen) - 1)
    )
    check("beat_now increases monotonically across playback", monotonic)

    # (b) Over the whole run the average rate must match beats-per-second.
    total_elapsed = n_samples / SAMPLE_HZ
    measured_rate = (beats_seen[-1] - beats_seen[0]) / total_elapsed
    check(
        f"rate is ~{BEATS_PER_SEC:.4f} beats/s (measured {measured_rate:.4f})",
        abs(measured_rate - BEATS_PER_SEC) < 0.01,
    )

    # (c) After 10 s of a 128 bpm track we expect 128/60 * 10 = 21.333 beats.
    expected_final = ground_truth_beats(DURATION_S)  # 21.333...
    check(
        f"after {DURATION_S:.0f}s beat_now ~= {expected_final:.2f} "
        f"(got {beats_seen[-1]:.4f})",
        abs(beats_seen[-1] - expected_final) < 0.05,
    )


def test_extrapolation_between_samples():
    """(d) Between two real samples, coasting on tempo must match ground truth.

    We feed a sample, then WITHOUT feeding another, ask for the beat at several
    instants up to the next sample time. The answer should track the true music
    position closely - this is the smoothing that lets the robot query at any
    moment, not only when Mixxx happens to send data.
    """
    lock = PhaseLock()

    # Anchor with two samples so a real tempo/phase is established.
    for i in range(2):
        elapsed = i / SAMPLE_HZ
        lock.update(
            T0 + elapsed,
            bpm=BPM,
            beat_distance=ground_truth_beat_distance(elapsed),
            playing=True,
        )

    last_elapsed = 1 / SAMPLE_HZ
    # Probe several points in the gap before the next (never-delivered) sample.
    for frac in (0.1, 0.3, 0.5, 0.7, 0.99):
        probe_elapsed = last_elapsed + frac / SAMPLE_HZ
        estimate = lock.beat_now(T0 + probe_elapsed)
        truth = ground_truth_beats(probe_elapsed)
        check(
            f"extrapolation at +{frac:.2f} sample matches truth "
            f"(est {estimate:.4f} vs {truth:.4f})",
            abs(estimate - truth) < 0.01,
        )


def test_freezes_when_paused():
    """(e) A paused deck must hold its beat still, not keep coasting."""
    lock = PhaseLock()

    # Play a little, then send a paused sample.
    lock.update(T0, bpm=BPM, beat_distance=0.25, playing=True)
    lock.update(T0 + 0.5, bpm=BPM, beat_distance=0.30, playing=False)

    frozen = lock.beat_now(T0 + 0.5)
    # Query well into the "future": a stopped deck must return the SAME value,
    # because no music time is passing.
    later = lock.beat_now(T0 + 5.0)
    check(
        f"paused beat_now freezes (t=0.5 -> {frozen:.4f}, t=5.0 -> {later:.4f})",
        frozen == later,
    )


def test_none_before_first_update():
    """A fresh lock has nothing honest to report until it's been fed."""
    lock = PhaseLock()
    check("beat_now is None before any update", lock.beat_now(T0) is None)
    check("bpm is None before any update", lock.bpm() is None)
    check("playing is False before any update", lock.playing() is False)


def test_snapshot_and_format_status():
    """snapshot() and format_status() produce sane, printable output."""
    d1 = PhaseLock()
    d1.update(T0, bpm=BPM, beat_distance=0.42, playing=True, playposition=0.1)
    d2 = PhaseLock()  # never updated -> everything unknown

    states = {1: d1.snapshot(T0), 2: d2.snapshot(T0)}
    check("snapshot returns a DeckState", isinstance(states[1], DeckState))
    check("played deck reports a bpm in snapshot", states[1].bpm == BPM)
    check("unfed deck reports beat None in snapshot", states[2].beat is None)

    line = format_status(states)
    check("status line marks deck 1 PLAY", "D1 PLAY" in line)
    check("status line marks deck 2 STOP", "D2 STOP" in line)
    check("status line uses ASCII '--' for unknowns", "--" in line)
    print(f"      sample status line: {line}")


def test_ignores_absurd_bpm():
    """A garbage bpm sample must not overwrite a previously good tempo."""
    lock = PhaseLock()
    lock.update(T0, bpm=BPM, beat_distance=0.1, playing=True)
    # A glitchy 0 / negative / huge bpm arrives - keep the last good one.
    lock.update(T0 + 0.1, bpm=0.0, beat_distance=0.2, playing=True)
    check("bpm 0 ignored, keeps last good tempo", lock.bpm() == BPM)
    lock.update(T0 + 0.2, bpm=99999.0, beat_distance=0.3, playing=True)
    check("absurd huge bpm ignored, keeps last good tempo", lock.bpm() == BPM)


def main():
    test_tracks_steady_playback()
    test_extrapolation_between_samples()
    test_freezes_when_paused()
    test_none_before_first_update()
    test_snapshot_and_format_status()
    test_ignores_absurd_bpm()
    print("\nALL PHASE-LOCK TESTS PASSED")


if __name__ == "__main__":
    main()
