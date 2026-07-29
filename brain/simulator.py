"""Phase 3 (simulator half): execute a planner.py routine LIVE in Mixxx, so you can hear
a transition before ever risking the arm.

WHERE THIS FITS
---------------
planner.py decides WHAT to do, entirely offline. This module is the "when" - it watches
song A's REAL live beat number (via Phase 1's phase_lock/midi_cc_feed, over the existing
beat-feed MIDI port) and, as that beat advances, sends the matching crossfader position
and hot-cue trigger into Mixxx over a SECOND MIDI port (RobotDJ_SimInput.midi.xml). Using
the live feed here - not blind wall-clock - is the same "awareness beats a fixed script"
principle Phase 1 exists for, just applied to the simulator instead of the eventual arm.

Two ports, two directions: the beat-feed port is Mixxx -> Python (read-only, Phase 1);
the sim-input port is Python -> Mixxx (write-only, this file). They must be different
loopMIDI ports - Mixxx can't run an input and output mapping on the same one.

WHY THE MATH (crossfader_value_at / to_midi_cc) IS SEPARATE FROM THE LIVE LOOP
-------------------------------------------------------------------------------
Same reasoning as phase_lock.py vs midi_cc_feed.py: the interpolation logic is
correctness-critical and needs to be provable without Mixxx or MIDI hardware (see
test_simulator.py). The live loop (run()) can't be unit-tested that way - it needs a real
Mixxx to talk to - so it's kept as thin as possible, calling only the tested functions.
"""
import argparse
import json
import time

try:
    import mido
    _MIDI_IMPORT_ERROR = None
except Exception as exc:  # ImportError, or rtmidi backend load failure
    mido = None
    _MIDI_IMPORT_ERROR = exc

from midi_cc_feed import CcBeatReader

# MIDI layout - must match RobotDJ_SimInput.midi.xml.
CROSSFADER_CC = 0x10
HOTCUE_NOTE_BY_DECK = {1: 0x00, 2: 0x01}

STATUS_HZ = 10.0  # how often to print/update while running - watchable, not flooding
STATUS_INTERVAL = 1.0 / STATUS_HZ


def crossfader_value_at(keyframes: list[dict], beat: float) -> float:
    """Piecewise-linear crossfader position (0.0 = full A, 1.0 = full B) at `beat`,
    interpolated between a routine's `crossfader_keyframes`. Clamps to the first/last
    keyframe's position before/after the covered range - a routine only defines the fade
    itself, not what happens before it starts or after it finishes.
    """
    if beat <= keyframes[0]["beat"]:
        return keyframes[0]["position"]
    if beat >= keyframes[-1]["beat"]:
        return keyframes[-1]["position"]

    for k0, k1 in zip(keyframes, keyframes[1:]):
        if k0["beat"] <= beat <= k1["beat"]:
            span = k1["beat"] - k0["beat"]
            frac = (beat - k0["beat"]) / span if span > 0 else 1.0
            return k0["position"] + frac * (k1["position"] - k0["position"])

    return keyframes[-1]["position"]  # unreachable given the clamps above; safe fallback


def to_midi_cc(position: float) -> int:
    """0.0..1.0 -> a 0..127 MIDI CC byte. Mixxx's own "normal" 7-bit scaling maps that
    straight onto the crossfader's native -1.0..+1.0 range, so no further conversion is
    needed here - see RobotDJ_SimInput.midi.xml.
    """
    clamped = max(0.0, min(1.0, position))
    return round(clamped * 127)


def _require_midi() -> None:
    if mido is None:
        raise SystemExit(
            "MIDI support isn't available: could not import 'mido'/'python-rtmidi'.\n"
            f"  underlying error: {_MIDI_IMPORT_ERROR}\n"
            "  fix: pip install -r requirements.txt"
        )


def run(
    routine: dict,
    beat_feed_port: str,
    sim_port: str,
    song_a_deck: int,
    song_b_deck: int,
) -> None:
    """Watch song_a_deck's live beat (over beat_feed_port) and drive the crossfader +
    song_b_deck's hot cue 1 (over sim_port) to match `routine`. Runs until Ctrl+C.

    Before running: song B must already be loaded on `song_b_deck` with hot cue 1 set at
    its entry point (see planner.py's docstring for why a hot cue, not a raw seek), and
    song A must already be playing on `song_a_deck`.
    """
    _require_midi()

    reader = CcBeatReader()
    keyframes = routine["crossfader_keyframes"]
    trigger_beat = routine["trigger_song_b_at_beat"]
    hotcue_note = HOTCUE_NOTE_BY_DECK[song_b_deck]
    triggered = False

    print(f"Reading live beat feed on {beat_feed_port!r} (deck {song_a_deck} = song A)")
    print(f"Sending simulator commands on {sim_port!r} (deck {song_b_deck} = song B)")
    print("Ctrl+C to stop.")

    with mido.open_input(beat_feed_port) as feed_in, mido.open_output(sim_port) as sim_out:
        last_status = 0.0
        try:
            while True:
                now = time.monotonic()

                for msg in feed_in.iter_pending():
                    reader.handle_message(msg, now)

                live_beat = reader.locks[song_a_deck].beat_now(now)
                if live_beat is None:
                    time.sleep(0.001)
                    continue

                position = crossfader_value_at(keyframes, live_beat)
                sim_out.send(
                    mido.Message("control_change", channel=0, control=CROSSFADER_CC,
                                 value=to_midi_cc(position))
                )

                if not triggered and live_beat >= trigger_beat:
                    sim_out.send(mido.Message("note_on", channel=0, note=hotcue_note, velocity=127))
                    sim_out.send(mido.Message("note_off", channel=0, note=hotcue_note, velocity=0))
                    triggered = True
                    print(f"\n  -> triggered song B hot cue (deck {song_b_deck}) at beat {live_beat:.2f}")

                if now - last_status >= STATUS_INTERVAL:
                    print(
                        f"\rA beat {live_beat:7.2f}  crossfader {position:4.2f}  "
                        f"{'[triggered]' if triggered else '[waiting]'}",
                        end="", flush=True,
                    )
                    last_status = now

                time.sleep(0.001)
        except KeyboardInterrupt:
            print()
            print("Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 3 simulator: execute a planner.py routine live in Mixxx."
    )
    parser.add_argument("--routine", required=True, metavar="FILE", help="routine JSON file (planner.plan_transition() output)")
    parser.add_argument("--beat-feed-port", required=True, metavar="NAME", help="loopMIDI port for the existing Phase 1 beat feed (Mixxx -> Python)")
    parser.add_argument("--sim-port", required=True, metavar="NAME", help="loopMIDI port for RobotDJ_SimInput (Python -> Mixxx)")
    parser.add_argument("--song-a-deck", type=int, choices=[1, 2], default=1, help="which deck song A is playing on (default 1)")
    parser.add_argument("--song-b-deck", type=int, choices=[1, 2], default=2, help="which deck song B is loaded on (default 2)")
    args = parser.parse_args()

    with open(args.routine, encoding="utf-8") as f:
        routine = json.load(f)

    run(routine, args.beat_feed_port, args.sim_port, args.song_a_deck, args.song_b_deck)


if __name__ == "__main__":
    main()
