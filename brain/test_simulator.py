"""Offline proof of simulator.py's correctness-critical math (crossfader_value_at,
to_midi_cc). No Mixxx, no MIDI hardware - this is the part that CAN be proven without
them; the live run() loop can't be (it needs a real Mixxx to talk to), so it isn't tested
here - see simulator.py's module docstring.

Run: python test_simulator.py
"""
from simulator import crossfader_value_at, to_midi_cc


def _check(label: str, condition: bool) -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    return condition


KEYFRAMES = [{"beat": 100, "position": 0.0}, {"beat": 132, "position": 1.0}]


def test_before_fade_holds_at_start_position() -> bool:
    print("test_before_fade_holds_at_start_position")
    return _check(
        "beat 0 (well before start) holds at 0.0",
        crossfader_value_at(KEYFRAMES, 0) == 0.0,
    )


def test_after_fade_holds_at_end_position() -> bool:
    print("test_after_fade_holds_at_end_position")
    return _check(
        "beat 999 (well after end) holds at 1.0",
        crossfader_value_at(KEYFRAMES, 999) == 1.0,
    )


def test_midpoint_is_halfway() -> bool:
    print("test_midpoint_is_halfway")
    midpoint_beat = (100 + 132) / 2
    value = crossfader_value_at(KEYFRAMES, midpoint_beat)
    return _check(f"beat {midpoint_beat} is ~0.5 (got {value})", abs(value - 0.5) < 1e-9)


def test_linear_interpolation_at_quarter_point() -> bool:
    print("test_linear_interpolation_at_quarter_point")
    # 8 beats into a 32-beat fade (100 -> 132) should be exactly 0.25 of the way.
    value = crossfader_value_at(KEYFRAMES, 108)
    return _check(f"beat 108 is ~0.25 (got {value})", abs(value - 0.25) < 1e-9)


def test_exact_endpoints() -> bool:
    print("test_exact_endpoints")
    ok = _check("beat 100 (start) is exactly 0.0", crossfader_value_at(KEYFRAMES, 100) == 0.0)
    ok &= _check("beat 132 (end) is exactly 1.0", crossfader_value_at(KEYFRAMES, 132) == 1.0)
    return ok


def test_to_midi_cc_range() -> bool:
    print("test_to_midi_cc_range")
    ok = _check("position 0.0 -> CC 0", to_midi_cc(0.0) == 0)
    ok &= _check("position 1.0 -> CC 127", to_midi_cc(1.0) == 127)
    ok &= _check("position 0.5 -> CC 64", to_midi_cc(0.5) == 64)
    return ok


def test_to_midi_cc_clamps_out_of_range_input() -> bool:
    print("test_to_midi_cc_clamps_out_of_range_input")
    ok = _check("position -0.5 clamps to CC 0", to_midi_cc(-0.5) == 0)
    ok &= _check("position 1.5 clamps to CC 127", to_midi_cc(1.5) == 127)
    return ok


def main() -> None:
    tests = [
        test_before_fade_holds_at_start_position,
        test_after_fade_holds_at_end_position,
        test_midpoint_is_halfway,
        test_linear_interpolation_at_quarter_point,
        test_exact_endpoints,
        test_to_midi_cc_range,
        test_to_midi_cc_clamps_out_of_range_input,
    ]
    results = [t() for t in tests]
    passed = sum(results)
    print(f"\n{passed}/{len(results)} tests passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
