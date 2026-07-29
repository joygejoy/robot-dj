"""FALLBACK feed: reconstruct the beat from Mixxx's MIDI CLOCK output.

WHERE THIS FITS IN PHASE 1
--------------------------
Phase 1's whole job is to let Python read Mixxx's LIVE beat and position with
low latency, so later phases can time the robot's physical moves to the real
music. Our PREFERRED way to get that data is OSC (see the OSC feed file), which
hands us tidy per-deck numbers like bpm and beat_distance directly.

But OSC isn't guaranteed. Whether a given Mixxx build/version exposes OSC, and
at what address, is uncertain. So we need a second, more universally available
way in. That's this file: the MIDI-clock fallback. Every Mixxx build can be told
to send MIDI out, so if OSC is missing we can still recover the tempo and beat
phase from a plain stream of MIDI timing pulses.

WHAT IS MIDI CLOCK? (the one fact this whole file rests on)
-----------------------------------------------------------
MIDI "clock" is a stream of tiny timing messages that musical gear sends to keep
in sync. The rule that matters: there are exactly 24 clock pulses per quarter
note - i.e. 24 pulses per BEAT. That number never changes; it's baked into the
MIDI standard (the constant PULSES_PER_BEAT below).

Two consequences we exploit:

  1. TEMPO comes from the SPACING of the pulses. If we time how long 24 pulses
     take, that's how long one beat takes, and bpm = 60 / (seconds per beat).
     Equivalently, bpm = 60 / (24 * seconds-between-pulses). We don't trust a
     single gap (it's jittery); we average over roughly a beat's worth of pulses.

  2. BEAT PHASE comes from COUNTING the pulses. Count pulses since the last beat
     line; (count mod 24) / 24 is exactly the "beat_distance" that Mixxx's OSC
     would have given us - 0.0 right on the beat, 0.5 halfway to the next one.
     That is the same 0..1 phase PhaseLock already knows how to smooth.

MIDI also has three transport messages we care about, sent alongside the clock:
  * START    - playback began from the top; reset our pulse counter to 0.
  * CONTINUE - playback resumed from where it was; keep counting.
  * STOP     - playback halted; mark the deck not-playing (freeze the estimate).

HOW MIXXX SENDS IT, AND loopMIDI
--------------------------------
Mixxx doesn't emit MIDI clock on its own for free; you enable it through a
controller OUTPUT mapping. The easy path on Windows is the bundled/community
"MIDI for light" output preset (or a small custom mapping) whose job is to spit
MIDI clock + beat pulses out of a MIDI port. Real MIDI ports are physical
sockets, so on a PC we fake one in software with loopMIDI
(https://www.tobias-erichsen.de/software/loopmidi.html): it creates a named
VIRTUAL port that behaves like a cable looped from Mixxx's output straight back
into this script's input. Mixxx writes to that port; we open the SAME port as an
INPUT and read the pulses. Nothing physical is plugged in anywhere.

So the data flow is:

    Mixxx  --(MIDI clock, output mapping)-->  loopMIDI virtual port
                                                     |
                                                     v
    this script (opens the port as INPUT) --> bpm + phase --> PhaseLock

THE BIG LIMITATION: MIDI CLOCK IS DECK-BLIND
--------------------------------------------
A MIDI clock stream carries ONE tempo and ONE running phase. It cannot, on its
own, tell you whether that beat belongs to Deck 1 or Deck 2 - there's simply no
"which deck" field in a clock pulse. Mixxx's master clock generally follows one
deck (the sync leader) at a time. So this fallback drives DECK 1 by default and
leaves Deck 2 "unknown". If you later build a custom output mapping that also
sends a distinguishing Note or CC per deck, there's a commented hook below
(_route_deck) showing where to branch on it. OSC does not have this limitation,
which is another reason it's the preferred path when available.

RUNTIME / CLOCK NOTE
--------------------
Like the OSC feed, this file owns the "when" (it reads time.monotonic() and
throttles its own printing), while PhaseLock owns the "where in the music". We
never do beat math here beyond the two conversions above - PhaseLock does the
smoothing/extrapolation. We only translate MIDI -> (bpm, beat_distance, playing)
and hand it over.

DEPENDENCIES
------------
Third-party: `mido` (the message layer) on top of the `python-rtmidi` backend
(the actual OS MIDI I/O). They're imported defensively below so this file still
parses and prints a friendly install hint on a machine that doesn't have them.
"""
import argparse
import time
from collections import deque

# --- Defensive third-party imports -----------------------------------------
# mido + python-rtmidi are what actually talk to the OS MIDI system. On a fresh
# machine they won't be installed yet, and we don't want this file to explode
# with a bare ImportError traceback that means nothing to a new developer. So we
# catch the failure, remember it, and only complain (with a fix) if/when someone
# actually tries to use the MIDI features. Everything that doesn't need MIDI -
# --help, importing this module, reading the docstring - keeps working.
try:
    import mido
    _MIDI_IMPORT_ERROR = None
except Exception as exc:  # ImportError, or rtmidi backend load failure
    mido = None
    _MIDI_IMPORT_ERROR = exc

from phase_lock import PhaseLock, format_status


# --- The one MIDI constant everything depends on ----------------------------
# 24 MIDI clock pulses per quarter note (per beat). This is fixed by the MIDI
# standard - see the module docstring. Every tempo and phase calculation here is
# just arithmetic around this number.
PULSES_PER_BEAT = 24

# How many recent pulses to average when estimating tempo. One beat's worth (24
# pulses = 24 intervals... actually 24 timestamps give 23 gaps, so we keep one
# extra) smooths out per-pulse timing jitter while still reacting within about a
# beat when the DJ nudges the tempo. Bigger = smoother but laggier.
TEMPO_WINDOW_PULSES = PULSES_PER_BEAT + 1

# How often to print the live status line. ~30 times/second is smooth to watch
# without flooding the terminal. This is a PRINT throttle only - we still read
# and count every incoming pulse the instant it arrives, so latency into
# PhaseLock is not affected by this number.
STATUS_HZ = 30.0
STATUS_INTERVAL = 1.0 / STATUS_HZ

# Which deck this fallback feeds. See "THE BIG LIMITATION" in the docstring:
# a single MIDI clock can't name a deck, so we commit to deck 1.
DEFAULT_DECK = 1


def list_ports() -> None:
    """Print every MIDI INPUT port the OS can see, then return.

    This is the first thing a new dev should run. loopMIDI ports show up here by
    the name you gave them in loopMIDI; you then pass that exact name to --port.
    If nothing sensible is listed, Mixxx/loopMIDI isn't set up yet - that's a
    configuration problem to fix before this script can read anything.
    """
    _require_midi()
    names = mido.get_input_names()
    if not names:
        print("No MIDI input ports found.")
        print(
            "Create one with loopMIDI and enable a MIDI-clock output mapping in "
            "Mixxx, then try again."
        )
        return
    print("Available MIDI input ports:")
    for name in names:
        print(f"  - {name}")


def _require_midi() -> None:
    """Raise a friendly, actionable error if mido/rtmidi didn't import.

    Called at the top of anything that actually needs MIDI. Keeping the check
    here (rather than crashing at import time) is what lets `--help` and plain
    importing of this module work on a machine without the libraries.
    """
    if mido is None:
        raise SystemExit(
            "MIDI support isn't available: could not import 'mido'/'python-rtmidi'.\n"
            f"  underlying error: {_MIDI_IMPORT_ERROR}\n"
            "  fix: install the Phase 1 dependencies, e.g.  pip install -r requirements.txt"
        )


class MidiClockReader:
    """Turns a raw MIDI message stream into (bpm, beat_distance, playing) and
    feeds one PhaseLock per deck.

    We keep only a short rolling window of recent pulse arrival times (for the
    tempo estimate) plus a running pulse counter (for the phase). That's all the
    state MIDI clock needs - PhaseLock does the heavy lifting of smoothing and
    extrapolating between updates.
    """

    def __init__(self) -> None:
        # One PhaseLock per deck, exactly like the OSC feed. We create both so
        # format_status() shows a tidy two-deck line, but this fallback only
        # ever feeds DEFAULT_DECK (see the deck-blind limitation). Deck 2 stays
        # "never updated", which PhaseLock correctly reports as unknown/STOP.
        self.locks: dict[int, PhaseLock] = {1: PhaseLock(), 2: PhaseLock()}

        # Arrival timestamps (monotonic seconds) of recent clock pulses. We take
        # the span from the oldest to newest and divide by the number of gaps to
        # get a smoothed seconds-per-pulse. deque with maxlen auto-drops the
        # oldest as new ones arrive - a self-trimming sliding window.
        self._pulse_times: deque[float] = deque(maxlen=TEMPO_WINDOW_PULSES)

        # Total clock pulses counted since the last START. Its value mod 24 is
        # our position within the current beat. It only resets on START (from the
        # top); CONTINUE deliberately keeps counting from where we left off.
        self._pulse_count = 0

        # Whether transport is currently running. Set by START/CONTINUE/STOP.
        # A clock pulse itself doesn't change this - some setups keep emitting
        # clock while stopped, and we don't want a stopped deck to look alive.
        self._playing = False

    def _current_bpm(self) -> float:
        """Best current tempo estimate from the pulse-spacing window.

        Returns 0.0 when we don't yet have enough pulses to measure a span.
        0.0 is deliberately "unknown": PhaseLock rejects any bpm <= 0 and keeps
        its last good value, so handing it 0.0 early on is safe and simply means
        "no new tempo info yet".
        """
        if len(self._pulse_times) < 2:
            return 0.0
        span = self._pulse_times[-1] - self._pulse_times[0]
        if span <= 0:
            return 0.0
        gaps = len(self._pulse_times) - 1          # N timestamps -> N-1 intervals
        seconds_per_pulse = span / gaps
        seconds_per_beat = seconds_per_pulse * PULSES_PER_BEAT
        return 60.0 / seconds_per_beat

    def _beat_distance(self) -> float:
        """Fractional phase 0..1 within the current beat, straight from the
        pulse count: (pulses since a beat line) / 24."""
        return (self._pulse_count % PULSES_PER_BEAT) / PULSES_PER_BEAT

    def _route_deck(self, msg) -> int:
        """Decide which deck a message belongs to. Today: always DEFAULT_DECK.

        A bare MIDI clock stream can't name a deck, so we can't do better than
        this without a richer mapping. If you later build a custom Mixxx output
        mapping that tags each deck - say, sending Note C-1 for deck 1 and C#-1
        for deck 2, or a CC whose channel selects the deck - branch here. For
        example:
            # if msg.type == 'note_on' and msg.note == 0:  return 1
            # if msg.type == 'note_on' and msg.note == 1:  return 2
        For now the argument is unused and we return the single deck we drive.
        """
        return DEFAULT_DECK

    def handle_message(self, msg, now: float) -> None:
        """Update internal state from one incoming MIDI message, then push the
        result into the relevant deck's PhaseLock.

        `now` is the caller-supplied monotonic timestamp (seconds) at which the
        message was read - passed straight through to PhaseLock so the whole
        system shares one clock, exactly as PhaseLock's contract expects.
        """
        deck = self._route_deck(msg)

        if msg.type == "clock":
            # A timing pulse: record its arrival (for tempo) and advance the
            # pulse counter (for phase).
            self._pulse_times.append(now)
            self._pulse_count += 1

        elif msg.type == "start":
            # Playback from the top: the very next pulse is beat-line 0, so reset
            # the counter and clear the tempo window (old gaps may be stale after
            # a jump). Mark playing.
            self._pulse_count = 0
            self._pulse_times.clear()
            self._playing = True

        elif msg.type == "continue":
            # Resume from where we paused: keep the pulse count so phase is
            # preserved; just mark playing again.
            self._playing = True

        elif msg.type == "stop":
            # Halt: freeze. PhaseLock, told playing=False, will hold the estimate
            # rather than extrapolate motion that isn't happening.
            self._playing = False

        else:
            # Anything else (active sensing, song position, sysex, notes we don't
            # map yet, ...) isn't part of the clock/transport we reconstruct from,
            # so we ignore it. NOTE for the curious: MIDI "song position pointer"
            # does carry an absolute position in MIDI-beats, but without the track
            # length we can't turn it into Mixxx's 0..1 playposition, so we don't
            # try - playposition stays None on this path.
            return

        # Feed the deck. We send this on every relevant message (each clock pulse
        # included) so PhaseLock always has a fresh anchor; between our updates it
        # extrapolates on its own. playposition is None because MIDI clock can't
        # give absolute track position (see above).
        self.locks[deck].update(
            now,
            bpm=self._current_bpm(),
            beat_distance=self._beat_distance(),
            playing=self._playing,
            playposition=None,
        )

    def snapshots(self, now: float) -> dict:
        """Current DeckState for every deck, keyed by deck number - ready to
        hand straight to format_status()."""
        return {deck: lock.snapshot(now) for deck, lock in self.locks.items()}


def run(port_name: str) -> None:
    """Open the virtual MIDI port as INPUT and stream the beat forever.

    This is the live loop; it is NOT called at import time and never during
    tests - it needs a real (loopMIDI) port and Mixxx sending clock, which the
    Phase 1 ground rules say we don't spin up here. It's written to be read now
    and run later.

    Shape mirrors runner.py: a tight polling loop rather than time.sleep()-based
    pacing. We drain every message that has arrived (so no pulse waits behind a
    print), then print the status line at most STATUS_HZ times a second.
    """
    _require_midi()

    reader = MidiClockReader()
    print(f"Opening MIDI input port: {port_name!r}")
    print("Reading MIDI clock. Ctrl+C to stop.")

    # A tiny idle nap keeps a truly-empty loop from pinning a CPU core. It's far
    # shorter than the time between pulses at any real tempo (24 pulses/beat at
    # 128bpm is a pulse every ~20ms), so it never delays reading a pulse.
    IDLE_NAP = 0.001

    last_print = 0.0
    # mido.open_input with no callback gives a port we can poll with
    # iter_pending() - it yields whatever messages have queued up without
    # blocking, which is what our polling loop wants.
    with mido.open_input(port_name) as port:
        try:
            while True:
                now = time.monotonic()

                # 1) Drain and handle everything waiting, timestamping each with
                #    the same `now`. They arrived within this loop tick, so one
                #    timestamp is plenty precise for beat work and keeps the
                #    shared-clock contract simple.
                got_any = False
                for msg in port.iter_pending():
                    reader.handle_message(msg, now)
                    got_any = True

                # 2) Throttled status print.
                if now - last_print >= STATUS_INTERVAL:
                    line = format_status(reader.snapshots(now))
                    # '\r' + end='' overwrites one line in place for a live,
                    # non-scrolling readout, matching the compact status design.
                    print("\r" + line, end="", flush=True)
                    last_print = now

                # 3) Only nap when idle, so we never add latency when pulses are
                #    actually flowing.
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
            "Robot DJ Phase 1 - MIDI-clock FALLBACK feed. Reconstructs bpm and "
            "beat phase from Mixxx's MIDI clock (24 pulses/beat) arriving on a "
            "virtual (loopMIDI) port, and feeds PhaseLock. Use only when OSC "
            "isn't available; OSC is the preferred, deck-aware path."
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
        help="exact name of the MIDI input port to open (e.g. a loopMIDI port)",
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
