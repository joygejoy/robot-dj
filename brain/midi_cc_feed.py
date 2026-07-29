"""LIVE feed: read the beat from our custom Mixxx "Robot DJ Beat Feed" mapping.

WHERE THIS FITS IN PHASE 1
--------------------------
Phase 1's job is to let Python read Mixxx's live beat/tempo with low latency so
later phases can time the robot to the real music. The preferred source was OSC,
but this Mixxx build has no OSC. The MIDI-clock fallback (midi_feed.py) doesn't
work either, because the only ready-made output mapping ("MIDI for light") sends
VU meters and a timecode but NOT MIDI clock or a continuous beat phase.

So we made our own Mixxx output mapping (mixxx_mapping/RobotDJ_BeatFeed*) that
sends exactly what phase_lock.py wants - beat_distance (0..1 phase), bpm, and a
play flag, PER DECK - as plain MIDI Control-Change (CC) messages. THIS file is
the Python end that decodes those CCs and feeds phase_lock. It is the MIDI twin
of live_feed.py (OSC): same data, different transport.

Unlike the deck-blind MIDI-clock fallback, this feed reports BOTH decks
independently, which is exactly what the later transition phases need.

THE CC LAYOUT (must match RobotDJ_BeatFeed-scripts.js)
------------------------------------------------------
All Control-Change on MIDI channel 1. Each deck owns a block of 4 CC numbers:

    field            deck 1 CC     deck 2 CC     meaning
    ---------------  -----------   -----------   -------------------------------
    beat_distance    20 (MSB)      24 (MSB)      14-bit phase, high 7 bits
                     21 (LSB)      25 (LSB)      14-bit phase, low 7 bits
    bpm              22            26            round(bpm - 50), 0..127
    playing          23            27            >=64 = playing, else stopped

beat_distance is 14-bit (two 7-bit CCs) for sub-beat precision. The mapping sends
the LSB LAST each frame, so we treat the LSB's arrival as "frame complete" and
only then push a fresh sample into phase_lock - guaranteeing the MSB, bpm and
play flag we combine with it are all from the same frame.

RUNTIME / CLOCK NOTE
--------------------
Like the other feeds, this file owns the "when" (reads time.monotonic() and
throttles its own printing); phase_lock owns the "where in the music". We only
translate CC -> (bpm, beat_distance, playing) and hand it over.

DEPENDENCIES
------------
Third-party `mido` on top of `python-rtmidi`, imported defensively so --help and
plain importing still work on a machine without them (same pattern as
midi_feed.py).
"""
import argparse
import time

# --- Defensive third-party imports (see midi_feed.py for the full rationale) ---
try:
    import mido
    _MIDI_IMPORT_ERROR = None
except Exception as exc:  # ImportError, or rtmidi backend load failure
    mido = None
    _MIDI_IMPORT_ERROR = exc

from phase_lock import PhaseLock, format_status


# --- The CC layout, mirrored from the Mixxx script --------------------------
# First CC number of each deck's 4-field block.
DECK_BASE_CC = {1: 20, 2: 24}

# We transmit bpm as (bpm - 50) to fit a 0..127 byte; add it back here.
BPM_OFFSET = 50

# Full-scale value of the 14-bit beat_distance the mapping sends.
BEAT_DISTANCE_FULL_SCALE = 16383  # 2**14 - 1

# How often to print the live status line (a PRINT throttle only - every CC is
# processed the instant it arrives). ~30 Hz is smooth without flooding.
STATUS_HZ = 30.0
STATUS_INTERVAL = 1.0 / STATUS_HZ

# Build a lookup: CC number -> (deck, field). Fields:
#   "bd_msb", "bd_lsb", "bpm", "play"
_CONTROL_MAP: dict[int, tuple[int, str]] = {}
for _deck, _base in DECK_BASE_CC.items():
    _CONTROL_MAP[_base + 0] = (_deck, "bd_msb")
    _CONTROL_MAP[_base + 1] = (_deck, "bd_lsb")
    _CONTROL_MAP[_base + 2] = (_deck, "bpm")
    _CONTROL_MAP[_base + 3] = (_deck, "play")


def list_ports() -> None:
    """Print every MIDI INPUT port the OS can see, then return.

    Run this first: your loopMIDI port shows up here by the name you gave it (on
    Windows often with a trailing number, e.g. 'MixxBeat 0'). Pass that exact
    name to --port.
    """
    _require_midi()
    names = mido.get_input_names()
    if not names:
        print("No MIDI input ports found.")
        print(
            "Create one with loopMIDI and load the 'Robot DJ Beat Feed' output "
            "mapping in Mixxx, then try again."
        )
        return
    print("Available MIDI input ports:")
    for name in names:
        print(f"  - {name}")


def _require_midi() -> None:
    """Raise a friendly, actionable error if mido/rtmidi didn't import."""
    if mido is None:
        raise SystemExit(
            "MIDI support isn't available: could not import 'mido'/'python-rtmidi'.\n"
            f"  underlying error: {_MIDI_IMPORT_ERROR}\n"
            "  fix: install the Phase 1 dependencies, e.g.  pip install -r requirements.txt"
        )


class CcBeatReader:
    """Turns the stream of Control-Change messages into (bpm, beat_distance,
    playing) per deck and feeds one PhaseLock each.

    We keep a tiny 'frame' of the latest raw bytes for each deck. Because the
    mapping sends the beat_distance LSB last, we finalise a frame (compute values
    and update PhaseLock) exactly when the LSB arrives - so the MSB/bpm/play we
    combine with it are always from the same frame.
    """

    def __init__(self) -> None:
        # One PhaseLock per deck, matching the other feeds.
        self.locks: dict[int, PhaseLock] = {1: PhaseLock(), 2: PhaseLock()}
        # Latest raw bytes per deck, awaiting the LSB that completes the frame.
        self._frames: dict[int, dict] = {
            1: {"bd_msb": 0, "bd_lsb": 0, "bpm": 0, "play": False},
            2: {"bd_msb": 0, "bd_lsb": 0, "bpm": 0, "play": False},
        }

    def handle_message(self, msg, now: float) -> None:
        """Update state from one incoming MIDI message. Only Control-Change
        messages in our CC map do anything; everything else is ignored."""
        if msg.type != "control_change":
            return
        entry = _CONTROL_MAP.get(msg.control)
        if entry is None:
            return

        deck, field = entry
        frame = self._frames[deck]

        if field == "bd_msb":
            frame["bd_msb"] = msg.value
        elif field == "bpm":
            frame["bpm"] = msg.value
        elif field == "play":
            frame["play"] = msg.value >= 64
        elif field == "bd_lsb":
            # LSB arrives last -> the frame is complete. Combine and push.
            frame["bd_lsb"] = msg.value
            beat_distance = (
                (frame["bd_msb"] << 7) | frame["bd_lsb"]
            ) / BEAT_DISTANCE_FULL_SCALE

            # Recover bpm. A byte of 0 means "no track / unknown tempo": we hand
            # phase_lock 0.0, which it treats as unknown (keeps its last good bpm,
            # or stays "--"), rather than inventing a bogus 50 bpm for an empty deck.
            bpm = (frame["bpm"] + BPM_OFFSET) if frame["bpm"] > 0 else 0.0

            self.locks[deck].update(
                now,
                bpm=bpm,
                beat_distance=beat_distance,
                playing=frame["play"],
                playposition=None,
            )

    def snapshots(self, now: float) -> dict:
        """Current DeckState for every deck, ready for format_status()."""
        return {deck: lock.snapshot(now) for deck, lock in self.locks.items()}


def run(port_name: str) -> None:
    """Open the virtual MIDI port as INPUT and stream the beat forever.

    Shape mirrors midi_feed.py: a tight polling loop that drains every pending
    message (so no sample waits behind a print), then prints a status line at
    most STATUS_HZ times a second.
    """
    _require_midi()

    reader = CcBeatReader()
    print(f"Opening MIDI input port: {port_name!r}")
    print("Reading Robot DJ beat feed (CC). Ctrl+C to stop.")

    IDLE_NAP = 0.001  # tiny nap only when idle, so we never delay a real message

    last_print = 0.0
    with mido.open_input(port_name) as port:
        try:
            while True:
                now = time.monotonic()

                got_any = False
                for msg in port.iter_pending():
                    reader.handle_message(msg, now)
                    got_any = True

                if now - last_print >= STATUS_INTERVAL:
                    line = format_status(reader.snapshots(now))
                    print("\r" + line, end="", flush=True)
                    last_print = now

                if not got_any:
                    time.sleep(IDLE_NAP)
        except KeyboardInterrupt:
            print()  # move off the in-place status line before exiting
            print("Stopped.")


def main() -> None:
    """Parse the CLI and dispatch. Two modes:
      --list-ports   inspect what MIDI inputs exist, then exit
      --port NAME    open NAME and stream the beat
    """
    parser = argparse.ArgumentParser(
        description=(
            "Robot DJ Phase 1 - live beat feed reading our custom 'Robot DJ Beat "
            "Feed' Mixxx output mapping. Decodes beat_distance + bpm + play from "
            "MIDI Control-Change messages on a virtual (loopMIDI) port and feeds "
            "PhaseLock. Reports both decks independently."
        )
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="list available MIDI input ports and exit",
    )
    parser.add_argument(
        "--port",
        metavar="NAME",
        help="exact name of the MIDI input port to open (e.g. your loopMIDI port)",
    )
    args = parser.parse_args()

    if args.list_ports:
        list_ports()
        return

    if not args.port:
        parser.error("give --port NAME (see --list-ports), or use --list-ports")

    run(args.port)


if __name__ == "__main__":
    main()
