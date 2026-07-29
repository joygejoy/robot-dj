"""Offline proof of analyzer.py's math, mirroring test_phase_lock.py's approach:
no real music file, no Mixxx, no hardware - we build a synthetic "click track" with
numpy where we KNOW the true bpm, downbeat phase, and section boundary, and check
that analyze_signal() recovers them.

A click track is just short percussive bursts placed at exact beat times - close
enough to real percussion for librosa's beat/onset/energy detectors to lock onto,
while keeping every ground-truth value exact and controllable.

Run: python test_analyzer.py
"""
import numpy as np

from analyzer import analyze_signal, PHRASE_BEATS

SR = 22050  # sample rate; lower than CD quality is plenty for a synthetic click track


def make_click_track(
    bpm: float,
    n_beats: int,
    downbeat_phase: int = 0,
    downbeat_boost: float = 2.5,
    boundary_at_beat: int | None = None,
    boundary_boost: float = 3.0,
    timbre_change_at_beat: int | None = None,
    timbre_layer_amp: float = 0.25,
    lead_in_beats: int = 4,
    sr: int = SR,
) -> np.ndarray:
    """A mono click track: one short decaying-sine "thump" per beat.

    - Beats at phase `downbeat_phase` (mod 4) are louder, simulating a kick drum
      landing on beat 1 of the bar.
    - If `boundary_at_beat` is given, every click from that beat onward is louder,
      simulating a real structural change (e.g. a new layer coming in) at that
      exact beat - our ground truth for the energy-based section-boundary test.
    - If `timbre_change_at_beat` is given, a quiet, CONTINUOUS higher-frequency
      tone starts underneath the clicks from that beat's time onward and holds
      through the end - simulating a new sustained instrument (a pad, a hi-hat
      loop) entering, same as a real track. Quiet enough not to trip the
      energy-ratio threshold - our ground truth for the spectral-only boundary
      test, proving the MFCC path catches a structural change RMS energy alone
      would miss (exactly the real-track gap this was added for - see
      PROGRESS.md). It has to be CONTINUOUS, not another short click: two earlier
      attempts used a second click (either replacing or layered onto the base
      click) and both failed, for two different reasons worth recording - (1)
      replacing the base click's frequency broke beat tracking for the whole back
      half of the track (the tracker's onset detector barely registered the new
      frequency as periodic), and (2) even layering a second click PRESERVED beat
      tracking only while quiet, but a click is a ~30ms event inside a mostly
      silent beat interval - the mean-MFCC comparison over an 8-beat window is
      dominated by that silence either side of it, so a barely-there transient
      doesn't move the average enough to be measurable. A sustained tone fills the
      space between beats too, which is both more measurable AND closer to what a
      real added instrument actually sounds like.
    - `lead_in_beats` of silence come before beat 0 (i.e. beat 0 does NOT start at
      sample 0). A click starting exactly at t=0 gives librosa's onset detector no
      run-up to lock its tempo/phase estimate onto, which cost several beats of
      accuracy at the very start in practice - real recordings essentially never
      start exactly on sample 0 either, so this also makes the fixture more
      realistic, not just more convenient.
    """
    beat_interval = 60.0 / bpm
    n_samples = int(((n_beats + lead_in_beats) * beat_interval + 1.0) * sr)
    y = np.zeros(n_samples, dtype=np.float64)

    click_len = int(0.03 * sr)
    t_click = np.arange(click_len) / sr
    base_click = np.exp(-t_click * 40) * np.sin(2 * np.pi * 150.0 * t_click)

    for i in range(n_beats):
        amp = 1.0
        if i % 4 == downbeat_phase:
            amp *= downbeat_boost
        if boundary_at_beat is not None and i >= boundary_at_beat:
            amp *= boundary_boost

        start = int((i + lead_in_beats) * beat_interval * sr)
        end = min(start + click_len, n_samples)
        y[start:end] += (amp * base_click)[: end - start]

    if timbre_change_at_beat is not None:
        change_start = int((timbre_change_at_beat + lead_in_beats) * beat_interval * sr)
        t_tail = np.arange(n_samples - change_start) / sr
        y[change_start:] += timbre_layer_amp * np.sin(2 * np.pi * 3000.0 * t_tail)

    return y


def _check(label: str, condition: bool) -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    return condition


def test_bpm_and_beats() -> bool:
    print("test_bpm_and_beats")
    true_bpm = 128.0
    y = make_click_track(true_bpm, n_beats=64)
    result = analyze_signal(y, SR)

    ok = _check(
        f"detected bpm ({result['bpm']:.2f}) within 3 of true bpm ({true_bpm})",
        abs(result["bpm"] - true_bpm) < 3.0,
    )
    ok &= _check(
        f"beat count ({len(result['beats'])}) close to true count (64)",
        # A sparse synthetic click track can cost the tracker a few edge beats
        # even when it's working correctly; this checks it's in the right
        # ballpark, not an exact match.
        abs(len(result["beats"]) - 64) <= 6,
    )
    return ok


def test_downbeat_phase() -> bool:
    print("test_downbeat_phase")
    true_bpm = 120.0
    true_phase = 2  # beat 1 of the bar is the 3rd click (index 2), not the 1st
    y = make_click_track(true_bpm, n_beats=64, downbeat_phase=true_phase)
    result = analyze_signal(y, SR)

    beat_interval = 60.0 / true_bpm
    lead_in_beats = 4  # matches make_click_track's default
    expected_first_downbeat_time = (lead_in_beats + true_phase) * beat_interval
    actual_first_downbeat_time = result["downbeats"][0]

    return _check(
        f"first downbeat at {actual_first_downbeat_time:.3f}s "
        f"(expected ~{expected_first_downbeat_time:.3f}s)",
        abs(actual_first_downbeat_time - expected_first_downbeat_time) < beat_interval / 2,
    )


def test_section_boundary_detected() -> bool:
    print("test_section_boundary_detected")
    true_bpm = 128.0
    boundary_beat = PHRASE_BEATS * 2  # a real change at the 2nd phrase-grid line
    n_beats = PHRASE_BEATS * 4
    y = make_click_track(true_bpm, n_beats=n_beats, boundary_at_beat=boundary_beat)
    result = analyze_signal(y, SR)

    boundaries = {s["start_beat"] for s in result["sections"]}
    close_match = any(abs(b - boundary_beat) <= 2 for b in boundaries)

    ok = _check(
        f"a section starts near beat {boundary_beat} (got starts: {sorted(boundaries)})",
        close_match,
    )
    ok &= _check(
        f"detected at least 2 sections (got {len(result['sections'])})",
        len(result["sections"]) >= 2,
    )
    return ok


def test_spectral_boundary_detected() -> bool:
    print("test_spectral_boundary_detected")
    true_bpm = 128.0
    boundary_beat = PHRASE_BEATS * 2
    n_beats = PHRASE_BEATS * 4
    # timbre_layer_amp=0.02 is quiet enough to keep the energy ratio well under
    # BOUNDARY_ENERGY_RATIO (empirically ~1.14, vs the 1.4 threshold) while still
    # being clearly audible as a new spectral element - this is the exact scenario
    # RMS-only detection missed on a real, mastered track.
    y = make_click_track(
        true_bpm, n_beats=n_beats, timbre_change_at_beat=boundary_beat, timbre_layer_amp=0.02
    )
    result = analyze_signal(y, SR)

    boundaries = {s["start_beat"] for s in result["sections"]}
    close_match = any(abs(b - boundary_beat) <= 2 for b in boundaries)

    return _check(
        f"a timbre-only change at beat {boundary_beat} is still detected "
        f"(got starts: {sorted(boundaries)})",
        close_match,
    )


def test_no_false_boundaries() -> bool:
    print("test_no_false_boundaries")
    true_bpm = 128.0
    n_beats = PHRASE_BEATS * 4
    y = make_click_track(true_bpm, n_beats=n_beats)  # uniform energy throughout
    result = analyze_signal(y, SR)

    return _check(
        f"a uniform track yields exactly 1 section (got {len(result['sections'])})",
        len(result["sections"]) == 1,
    )


def main() -> None:
    tests = [
        test_bpm_and_beats,
        test_downbeat_phase,
        test_section_boundary_detected,
        test_spectral_boundary_detected,
        test_no_false_boundaries,
    ]
    results = [t() for t in tests]
    passed = sum(results)
    print(f"\n{passed}/{len(results)} tests passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
