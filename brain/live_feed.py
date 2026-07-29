"""Listens to Mixxx over OSC and turns its live control values into a smooth,
always-answerable beat/phase estimate for each deck. This is the PREFERRED way to
get the music position into Robot DJ (the MIDI-clock feed is the fallback).

WHAT IS OSC, IN PLAIN ENGLISH?
------------------------------
OSC ("Open Sound Control") is just a way for one program to send another program
little labelled messages over the network - usually over UDP, usually all on the
same computer (127.0.0.1, the "localhost" loopback address). Each message has:

  * an ADDRESS, which looks like a file path, e.g. "/[Channel1]/bpm", and
  * zero or more ARGUMENTS, which are the actual values, e.g. 128.0.

The key thing to get straight about who-talks-to-who:

  * MIXXX is the CLIENT here. When you enable OSC output in Mixxx and play a
    track, Mixxx PUSHES messages out ("hey, [Channel1]'s bpm is now 128.0", "hey,
    its beat_distance is now 0.42") many times a second.
  * THIS SCRIPT is the SERVER. It sits and LISTENS on a port (a numbered mailbox
    on your machine) and reacts to each message Mixxx pushes. It never asks Mixxx
    for anything; it just receives.

So the data only flows one direction: Mixxx -> us. All we do is catch those
values and hand them to a PhaseLock (see phase_lock.py) which smooths them into a
running beat number the robot can later time its moves to.

THE DISCOVERY PROBLEM (read this before you run anything for real)
------------------------------------------------------------------
There is one genuinely annoying wrinkle: the EXACT address strings Mixxx uses are
VERSION-DEPENDENT. Different Mixxx builds and different OSC-mapping setups emit
different address formats - some wrap the group in brackets ("/[Channel1]/bpm"),
some don't ("/Channel1/bpm"), some nest it differently. We must NOT just assume a
format and hardcode it, because if we guess wrong we'll sit here receiving
messages and silently ignoring every one of them, and it'll look like nothing is
working for no obvious reason.

So this script has two modes:

  1. DISCOVERY MODE ( --discovery ):
     Print EVERY incoming OSC message - its raw address and its arguments -
     exactly as Mixxx sends it, and do nothing else. You run this once, play a
     track in Mixxx, and watch the terminal to SEE with your own eyes which
     addresses carry playposition, bpm, beat_distance and play on YOUR build.

  2. NORMAL MODE (the default):
     Actually parse those addresses and feed the values into the PhaseLock for
     each deck, printing a live status line. All of the "which address means
     what" logic lives in ONE function, parse_address(), which is heavily
     commented and pre-filled with reasonable guesses. After you've run discovery
     and seen the real formats, parse_address() is the one place you tweak.

WHY ACCUMULATE VALUES (an important subtlety)
---------------------------------------------
Mixxx sends each control as its OWN separate message. One message carries only
the bpm; a different message carries only the beat_distance; another only 'play'.
But PhaseLock.update() wants bpm AND beat_distance AND playing together, in one
call. So for each deck we REMEMBER the latest value we've seen for every control,
and every time any relevant message arrives we re-issue update() using the newest
known value of each. That way a fresh beat_distance is always paired with the most
recent bpm and play state, even though they arrived in different packets.

RUNNING IT (for reference - this file defines the program; you run it yourself):
    First install the dependency:   pip install -r requirements.txt
    See the raw addresses:          python live_feed.py --discovery
    Run the real feed:              python live_feed.py
    If your Mixxx uses another port: python live_feed.py --port 9001
"""
import argparse
import time

# --- Defensive third-party import ------------------------------------------
# python-osc is NOT part of the standard library, so on a machine that hasn't
# run `pip install -r requirements.txt` yet, importing it would blow up with a
# bare ModuleNotFoundError the moment this file is loaded - even just to read
# --help. We'd rather the file always PARSE and give a friendly, actionable
# message. So we try the import, and if it fails we stash the error and only
# complain (with instructions) if/when someone actually tries to start the
# server. Everything that doesn't touch OSC - parse_address(), --help, importing
# this module in a test - keeps working regardless.
try:
    from pythonosc import dispatcher as osc_dispatcher
    from pythonosc import osc_server
    _OSC_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - depends on the environment
    osc_dispatcher = None
    osc_server = None
    _OSC_IMPORT_ERROR = exc

# PhaseLock and friends are our own stdlib-only core (phase_lock.py). These are
# the real names/signatures from that module - see it for the full reasoning.
from phase_lock import PhaseLock, format_status


# --- Configuration constants -----------------------------------------------

# How many times per second to reprint the live status line. Mixxx can fire OSC
# messages far faster than that, and repainting the terminal on every single
# packet would flicker and waste effort without telling a human anything new. ~30
# Hz is smooth to the eye and matches the rate the robot side will care about.
STATUS_HZ = 30.0
STATUS_INTERVAL = 1.0 / STATUS_HZ

# The Mixxx groups we care about, mapped to the deck numbers the rest of the app
# uses. Mixxx calls its two main decks "[Channel1]" and "[Channel2]"; we track
# them as deck 1 and deck 2. (Mixxx also has [Channel3]/[Channel4], samplers,
# etc., but Robot DJ only plays the two-deck FLX4 layout, so we ignore the rest.)
DECK_FOR_CHANNEL = {1: 1, 2: 2}

# The four control keys we actually consume. Anything else Mixxx sends is noise
# to us and gets dropped. These strings are the Mixxx "control" names and are the
# stable part of the address - it's the GROUP wrapping (brackets or not) and the
# overall layout that varies between builds, not these leaf names.
WANTED_CONTROLS = ("playposition", "bpm", "beat_distance", "play")


def parse_address(address):
    """Decide which deck and which control an OSC address refers to.

    Returns a tuple (deck_number, control_name) - e.g. (1, "bpm") - or None if
    this address is something we don't care about.

    >>> VERIFY THESE WITH --discovery <<<
    This function is the ENTIRE "which address means what" brain of the feed, and
    it's deliberately the one spot you edit after seeing your Mixxx build's real
    output. The logic below is written to be forgiving of the common format
    variations rather than to match one exact string, because the address scheme
    is version-dependent (see the module docstring). But "forgiving" is still a
    guess - once --discovery shows you the truth, come back and tighten this up.

    HOW IT WORKS
    ------------
    OSC addresses are slash-separated, like a file path. Real-world Mixxx examples
    for the SAME logical value ([Channel1]'s bpm) that different setups emit:

        /[Channel1]/bpm
        /Channel1/bpm
        /mixxx/[Channel1]/bpm

    The two moving parts are (a) how the channel/group is written, and (b) how
    deep in the path it sits. So instead of hardcoding one whole address, we split
    the path into its segments and hunt for two things independently:

        * a segment that names a channel we track (Channel1 -> deck 1, etc.),
          tolerating the optional square brackets, and
        * a segment that is one of our WANTED_CONTROLS.

    If we find both, we've identified the message. If either is missing, we return
    None and the caller ignores the message.
    """
    # "/[Channel1]/bpm" -> ["", "[Channel1]", "bpm"]; drop the empty pieces that
    # the leading slash (or any doubled slash) produces.
    segments = [seg for seg in address.split("/") if seg]

    deck = None
    control = None
    for seg in segments:
        # Normalise a group segment by stripping the optional square brackets, so
        # "[Channel1]" and "Channel1" are treated identically. This is the single
        # most common format difference between Mixxx builds.
        bare = seg.strip("[]")

        # Is this segment one of our channels? We check each known channel number
        # by name so we never mistake "[Channel3]" (which we don't track) for a
        # deck we do.
        for channel_num, deck_num in DECK_FOR_CHANNEL.items():
            if bare == f"Channel{channel_num}":
                deck = deck_num
                break

        # Is this segment one of the controls we consume?
        if bare in WANTED_CONTROLS:
            control = bare

    if deck is not None and control is not None:
        return (deck, control)
    return None


class DeckFeed:
    """Holds one deck's PhaseLock plus the latest raw value of each control.

    We need this little bag of "most recent value seen" because - as explained in
    the module docstring - Mixxx sends each control in its own message, but
    PhaseLock.update() wants them all together. So we cache the newest bpm,
    beat_distance, play and playposition here and re-send the full set to the lock
    whenever any of them changes.
    """

    def __init__(self):
        self.lock = PhaseLock()
        # None means "we haven't heard this control from Mixxx yet". We keep them
        # None (rather than defaulting to 0) so we can tell "genuinely unknown"
        # apart from "really is zero", and so we don't feed a fake 0 bpm into the
        # lock before Mixxx has told us the real tempo.
        self.bpm = None
        self.beat_distance = None
        self.play = None
        self.playposition = None

    def apply(self, control, value, now):
        """Record one freshly-arrived control value and push the combined set into
        the PhaseLock.

        `now` is a monotonic timestamp the caller supplies (PhaseLock never reads
        the clock itself - that keeps it deterministic and testable).
        """
        # Store whichever single control this message carried.
        if control == "bpm":
            self.bpm = value
        elif control == "beat_distance":
            self.beat_distance = value
        elif control == "play":
            self.play = value
        elif control == "playposition":
            self.playposition = value

        # Now hand PhaseLock the best current picture. We fall back to safe
        # neutral values for anything we haven't heard yet:
        #   * bpm 0.0 -> PhaseLock rejects it as out-of-range and keeps its last
        #     good tempo (or stays "unknown"), which is exactly what we want.
        #   * beat_distance 0.0 -> harmless neutral phase until the real one lands.
        #   * play unknown -> treat as not playing; we won't count phantom beats
        #     for a deck we haven't confirmed is rolling.
        self.lock.update(
            now,
            bpm=self.bpm if self.bpm is not None else 0.0,
            beat_distance=self.beat_distance if self.beat_distance is not None else 0.0,
            playing=bool(self.play) if self.play is not None else False,
            playposition=self.playposition,
        )


def _require_osc():
    """Raise a friendly, instructive error if python-osc isn't installed.

    Called only at the moment we're about to actually use the library, so that
    simply importing this module (e.g. from a test of parse_address) never trips
    over a missing dependency.
    """
    if _OSC_IMPORT_ERROR is not None:
        raise SystemExit(
            "This feed needs the 'python-osc' package, which isn't installed.\n"
            "Fix it by running:  pip install -r requirements.txt\n"
            f"(underlying import error: {_OSC_IMPORT_ERROR})"
        )


def make_discovery_dispatcher():
    """Build a dispatcher that simply PRINTS every message Mixxx sends.

    This is the whole of discovery mode. We attach a single "default handler" -
    the callback the dispatcher runs for any address that has no more specific
    handler registered - and since we register nothing else, EVERY incoming
    message lands here and gets printed verbatim. That's the point: see the real,
    unfiltered address strings your Mixxx build emits.
    """
    _require_osc()

    def show(address, *args):
        # Print the raw address and its arguments exactly as received. This is the
        # ground truth you use to fix up parse_address() for your build.
        print(f"{address}    args={list(args)}")

    disp = osc_dispatcher.Dispatcher()
    disp.set_default_handler(show)
    return disp


def make_feed_dispatcher(decks, status_state):
    """Build the NORMAL-mode dispatcher: parse each message and feed a PhaseLock.

    `decks` is a dict {deck_number: DeckFeed}. `status_state` is a tiny mutable
    holder used to throttle the live status printout (see below) - we keep it in a
    dict so the nested handler can update it without `nonlocal` gymnastics.

    Like discovery mode, we route EVERYTHING through one default handler rather
    than mapping specific addresses. That's deliberate: because the exact
    addresses are uncertain, it's far more robust to receive every message and let
    parse_address() decide what it is, than to pre-register a fixed set of address
    strings that might not match what Mixxx actually sends.
    """
    _require_osc()

    def handle(address, *args):
        # Timestamp the moment we received this message. time.monotonic() only ever
        # moves forward and isn't affected by the system clock being adjusted,
        # which is exactly what PhaseLock's extrapolation wants.
        now = time.monotonic()

        parsed = parse_address(address)
        if parsed is None:
            # Not a control we care about (or an address format parse_address
            # doesn't recognise yet - if you expected this one to match, that's
            # your cue to run --discovery and tweak parse_address).
            return

        deck_num, control = parsed

        # OSC arguments arrive as a tuple; the controls we want each carry a single
        # numeric value. If a message somehow arrived with no argument, skip it
        # rather than crash.
        if not args:
            return
        value = args[0]

        decks[deck_num].apply(control, value, now)

        # Throttled live status. We reprint at most STATUS_HZ times a second (see
        # the constant's comment) - checking elapsed time here, rather than on a
        # separate timer thread, keeps everything single-threaded and simple. Since
        # Mixxx fires messages well above 30 Hz while a track plays, this handler
        # runs often enough to keep the line fresh.
        if now - status_state["last_print"] >= STATUS_INTERVAL:
            status_state["last_print"] = now
            snapshots = {n: d.lock.snapshot(now) for n, d in decks.items()}
            # \r returns the cursor to the start of the line and end="" stops a
            # newline, so the status overwrites itself in place instead of scrolling
            # - a single, calm, live-updating line while you watch Phase 1 work.
            print("\r" + format_status(snapshots), end="", flush=True)

    disp = osc_dispatcher.Dispatcher()
    disp.set_default_handler(handle)
    return disp


def build_arg_parser():
    """Define the command-line options. Kept in its own function so it can be
    unit-tested or reused without side effects."""
    parser = argparse.ArgumentParser(
        description="Receive Mixxx's live deck values over OSC and estimate the "
        "current beat/phase for each deck."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Network address to LISTEN on. Default 127.0.0.1 (localhost) is "
        "right when Mixxx runs on this same machine, which is the usual setup.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        # IMPORTANT: this MUST match the port set in Mixxx's own OSC output config.
        # Mixxx decides where it pushes to; we just listen there. If they disagree,
        # you'll receive absolutely nothing and everything will look silently dead.
        help="UDP port to listen on. MUST match the port configured in Mixxx's "
        "OSC output settings. Default 9000.",
    )
    parser.add_argument(
        "--discovery",
        action="store_true",
        help="Discovery mode: print every incoming OSC address and its arguments "
        "and nothing else. Run this, play a track in Mixxx, and watch which "
        "addresses carry playposition/bpm/beat_distance/play so you can verify "
        "(and if needed fix) parse_address() for your Mixxx build.",
    )
    return parser


def main(argv=None):
    """Parse arguments, build the right dispatcher, and run the OSC server.

    NOTE: this is what starts the actual network listener. It's defined here so
    the file is a complete, runnable program - but you run it yourself once
    python-osc is installed and Mixxx is configured; nothing runs it for you.
    """
    _require_osc()
    args = build_arg_parser().parse_args(argv)

    if args.discovery:
        print("=" * 70)
        print("OSC DISCOVERY MODE")
        print("=" * 70)
        print(
            "Now listening for raw OSC messages. Go to Mixxx, make sure its OSC\n"
            "output is enabled and pointed at this host/port, and PLAY A TRACK.\n"
            "Every message Mixxx pushes will be printed below, exactly as sent.\n"
            "\n"
            "Watch for the addresses that carry these four values as the track\n"
            "plays and as you press play/pause:\n"
            "    playposition  - climbs 0..1 across the whole track\n"
            "    bpm           - the tempo, e.g. 128.0\n"
            "    beat_distance - flickers 0..1, resetting every beat\n"
            "    play          - 1 while playing, 0 when paused\n"
            "\n"
            "Then compare those real addresses against parse_address() in this\n"
            "file and adjust it if they don't match. Press Ctrl+C to stop.\n"
        )
        disp = make_discovery_dispatcher()
    else:
        print(
            "Listening for Mixxx OSC. Play a track; the live beat should start\n"
            "moving below. Seeing nothing? The addresses may not match this\n"
            "build - rerun with --discovery to inspect them. Ctrl+C to stop.\n"
        )
        # One DeckFeed (PhaseLock + latest values) per deck we track.
        decks = {deck_num: DeckFeed() for deck_num in DECK_FOR_CHANNEL.values()}
        # Mutable holder for the throttle timestamp; starts far in the past so the
        # very first message prints immediately.
        status_state = {"last_print": 0.0}
        disp = make_feed_dispatcher(decks, status_state)

    # Create and run the UDP server. ThreadingOSCUDPServer handles each datagram
    # as it arrives; serve_forever() blocks here until you Ctrl+C. We catch that
    # so shutdown is tidy rather than dumping a KeyboardInterrupt traceback.
    server = osc_server.ThreadingOSCUDPServer((args.host, args.port), disp)
    print(f"Serving on {args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
