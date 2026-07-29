"""Offline proof of planner.py, same philosophy as test_phase_lock.py /
test_analyzer.py: no Mixxx, no real songs - just small fake analyzer-shaped dicts with
known bpm/beat counts, checking plan_transition() does the right thing (and rejects the
wrong thing).

Run: python test_planner.py
"""
from planner import plan_transition, MAX_BPM_MISMATCH_FRACTION


def _check(label: str, condition: bool) -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    return condition


def _fake_song(bpm: float, n_beats: int) -> dict:
    beat_interval = 60.0 / bpm
    return {"bpm": bpm, "beats": [i * beat_interval for i in range(n_beats)]}


def test_basic_routine_shape() -> bool:
    print("test_basic_routine_shape")
    song_a = _fake_song(128.0, 200)
    song_b = _fake_song(128.0, 200)
    routine = plan_transition(song_a, song_b, start_beat_a=100, entry_beat_b=0, crossfade_beats=32)

    ok = _check("song_a start_beat is 100", routine["song_a"]["start_beat"] == 100)
    ok &= _check(
        "crossfader_keyframes go from 0.0 at beat 100 to 1.0 at beat 132",
        routine["crossfader_keyframes"] == [
            {"beat": 100, "position": 0.0},
            {"beat": 132, "position": 1.0},
        ],
    )
    ok &= _check(
        "trigger_song_b_at_beat matches start_beat_a",
        routine["trigger_song_b_at_beat"] == 100,
    )
    ok &= _check("song_b hotcue defaults to 1", routine["song_b"]["hotcue"] == 1)
    return ok


def test_rejects_out_of_range_start_beat() -> bool:
    print("test_rejects_out_of_range_start_beat")
    song_a = _fake_song(128.0, 50)
    song_b = _fake_song(128.0, 50)
    try:
        plan_transition(song_a, song_b, start_beat_a=999, crossfade_beats=32)
        return _check("raises ValueError for an out-of-range start_beat_a", False)
    except ValueError:
        return _check("raises ValueError for an out-of-range start_beat_a", True)


def test_rejects_crossfade_past_song_end() -> bool:
    print("test_rejects_crossfade_past_song_end")
    song_a = _fake_song(128.0, 110)
    song_b = _fake_song(128.0, 200)
    try:
        # start at beat 100, but only 10 beats of song A remain - a 32-beat fade won't fit
        plan_transition(song_a, song_b, start_beat_a=100, crossfade_beats=32)
        return _check("raises ValueError when the fade runs past song A's end", False)
    except ValueError:
        return _check("raises ValueError when the fade runs past song A's end", True)


def test_rejects_mismatched_tempo() -> bool:
    print("test_rejects_mismatched_tempo")
    song_a = _fake_song(128.0, 200)
    song_b = _fake_song(140.0, 200)  # ~9% off - well past MAX_BPM_MISMATCH_FRACTION
    try:
        plan_transition(song_a, song_b, start_beat_a=100, crossfade_beats=32)
        return _check("raises ValueError for mismatched bpm", False)
    except ValueError:
        return _check("raises ValueError for mismatched bpm", True)


def test_accepts_near_matched_tempo() -> bool:
    print("test_accepts_near_matched_tempo")
    song_a = _fake_song(128.0, 200)
    # Just inside the tolerance - should NOT raise.
    song_b = _fake_song(128.0 * (1 + MAX_BPM_MISMATCH_FRACTION * 0.5), 200)
    try:
        plan_transition(song_a, song_b, start_beat_a=100, crossfade_beats=32)
        return _check("does not raise for a small, in-tolerance bpm difference", True)
    except ValueError:
        return _check("does not raise for a small, in-tolerance bpm difference", False)


def main() -> None:
    tests = [
        test_basic_routine_shape,
        test_rejects_out_of_range_start_beat,
        test_rejects_crossfade_past_song_end,
        test_rejects_mismatched_tempo,
        test_accepts_near_matched_tempo,
    ]
    results = [t() for t in tests]
    passed = sum(results)
    print(f"\n{passed}/{len(results)} tests passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
