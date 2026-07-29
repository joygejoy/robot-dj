"""Turns Mixxx's occasional, jittery beat readings into a SMOOTH, always-answerable
estimate of "where are we in the music right now?"

WHY THIS EXISTS
---------------
Later phases of Robot DJ will time the MECA500's physical moves to the real music.
But the music data we get from Mixxx has two problems:

  1. It arrives INTERMITTENTLY. Depending on the transport (OSC or MIDI clock),
     we get updates at irregular intervals - maybe 30 times a second, maybe
     bunched up, maybe with gaps. The robot, though, might ask "what beat are we
     on?" at any instant in between those updates.

  2. It's JITTERY. Timestamps wobble, samples can arrive late, and a value like
     Mixxx's 'beat_distance' (how far we are between the last beat and the next,
     0..1) resets to ~0 every single beat, so on its own it can't tell you
     WHICH beat you're on - only the phase within one.

This module solves both. You feed a PhaseLock the raw samples as they come in,
and it hands back a single ever-growing floating-point "beat" number on demand:
the integer part counts whole beats since we started watching a deck, and the
fractional part is the phase inside the current beat (0.0 = right on the beat,
0.5 = exactly halfway to the next one). Between samples it EXTRAPOLATES using the
known tempo, so the answer is smooth even though the inputs are lumpy.

DESIGN NOTE: standard library ONLY.
This file deliberately imports nothing third-party. It is the correctness-critical
core, and it must be unit-testable on any machine with plain `python`, with no
Mixxx running and no OSC/MIDI hardware present. Anything that touches the network
or MIDI lives in the "feed" files, not here.

CLOCK NOTE: this module never reads the clock itself.
Every method that needs "the current time" takes a `now` argument (a monotonic
timestamp in seconds) from the caller. That keeps the whole thing deterministic:
the tests can feed a fake, hand-controlled clock and get exactly repeatable
results, and the real program passes time.monotonic().
"""
from dataclasses import dataclass


# --- Tuning constants -------------------------------------------------------
# These live at module scope (not buried in the methods) so they're easy to find
# and reason about, and so the test file can refer to the same reasoning.

# A beat "wraps" when beat_distance jumps from near-the-top back down to
# near-zero (e.g. 0.98 -> 0.02) - that's Mixxx crossing a beat line. We require
# the OLD value to be above this and the NEW value below WRAP_LOW to count it as
# a genuine wrap, rather than reacting to ordinary sample-to-sample noise.
WRAP_HIGH = 0.7
WRAP_LOW = 0.3

# Sanity bounds on tempo. Real DJ tracks essentially never sit outside this, so a
# bpm at or below 0, or above 400, is a glitch/garbage sample (or an unset value
# arriving as 0). We refuse to adopt it rather than let it poison the estimate -
# a bogus bpm would make extrapolation between samples fly off in a wrong
# direction. 400 is comfortably above double-time drum'n'bass (~170-180) even if
# Mixxx ever reports a doubled value.
MIN_BPM = 0.0
MAX_BPM = 400.0


@dataclass
class DeckState:
    """A plain, printable snapshot of one deck at one instant.

    This is what the rest of the program consumes - it never has to know about
    PhaseLock's internal bookkeeping. `beat` is the same combined number
    described in the module docstring: whole beats counted so far, plus the
    fractional phase within the current beat.

    Fields are Optional (may be None) because at startup, or before Mixxx has
    told us anything about a deck, we genuinely don't know the tempo or position
    yet - and it's safer to say "unknown" than to invent a zero.
    """
    playing: bool
    bpm: float | None
    beat: float | None
    # The last raw 'playposition' (0..1 across the whole track) we were told.
    # Kept ONLY for logging/diagnostics - the beat estimate does not depend on
    # it, because playposition alone can't give sub-beat phase at useful
    # resolution. Handy when eyeballing logs to confirm a deck really is moving.
    raw_position: float | None


class PhaseLock:
    """Tracks and smoothly estimates the beat position of ONE deck.

    Create one instance per Mixxx deck (one for [Channel1], one for [Channel2]).
    Call update() every time a fresh sample arrives; call beat_now() whenever you
    actually need the current beat number (which may be far more often, or at
    different moments, than samples arrive).

    Internally we store only the LAST accepted sample plus a running integer beat
    counter. We don't keep a long history: the whole point is that given the last
    known phase and the tempo, simple linear extrapolation is an excellent model
    of a track playing at steady speed, so one anchor point is enough.
    """

    def __init__(self) -> None:
        # Have we ever accepted a sample? Until we have, every query returns None
        # rather than a made-up value.
        self._initialised = False

        # The running count of WHOLE beats since we started tracking this deck.
        # This is what survives across beat wraps - beat_distance keeps resetting
        # to 0 each beat, but this only ever climbs.
        self._beat_count = 0

        # Everything about the last accepted sample. "last" = the anchor we
        # extrapolate forward from.
        self._last_now: float | None = None
        self._last_beat_distance: float | None = None
        self._last_bpm: float | None = None
        self._last_playing = False
        self._last_position: float | None = None

    # -- Feeding in data -----------------------------------------------------

    def update(
        self,
        now: float,
        *,
        bpm: float,
        beat_distance: float,
        playing: bool,
        playposition: float | None = None,
    ) -> None:
        """Record one fresh sample from Mixxx.

        `now`           monotonic timestamp (seconds) supplied by the caller.
        `bpm`           the deck's current tempo.
        `beat_distance` fractional phase 0..1 between the previous and next beat.
        `playing`       True if the deck is actually playing (Mixxx 'play' == 1).
        `playposition`  optional 0..1 position across the whole track (logging).

        Keyword-only (the `*`) on purpose: at the call site
        `update(now, bpm=..., beat_distance=..., playing=...)` reads unambiguously,
        and nobody can accidentally swap bpm and beat_distance by passing them
        positionally - they're both bare floats and that mix-up would be silent
        and nasty.
        """
        # 1) Validate the tempo before we trust it. A garbage bpm is worse than a
        #    stale one, because we extrapolate with bpm - a wrong tempo makes the
        #    beat number drift wrongly between every pair of samples. If the new
        #    bpm is absurd, keep whatever good bpm we already had (if any) and
        #    otherwise leave the deck's tempo unknown.
        if MIN_BPM < bpm <= MAX_BPM:
            accepted_bpm = bpm
        else:
            accepted_bpm = self._last_bpm  # may be None; that's fine - "unknown"

        # 2) Detect beat wrap(s) and advance the whole-beat counter.
        #    Only meaningful once we already have a previous sample AND the deck
        #    is (and was) playing - a paused deck's beat_distance shouldn't move,
        #    and if it does we don't want to count phantom beats.
        if (
            self._initialised
            and self._last_beat_distance is not None
            and self._last_now is not None
            and playing
            and self._last_playing
        ):
            # (a) The classic single wrap: phase was high, now it's low. Mixxx
            #     just crossed a beat line, so at least one whole beat elapsed.
            wrapped = (
                self._last_beat_distance > WRAP_HIGH and beat_distance < WRAP_LOW
            )

            # (b) How many beats does ELAPSED TIME say should have gone by? With
            #     sparse or slow updates, more than one beat can pass between two
            #     samples, and a single high->low check would only ever count one,
            #     silently losing beats. If we have a real tempo, use it to figure
            #     out the true number of whole beats between the two anchor phases
            #     and jump the counter by that many so nothing is dropped.
            if accepted_bpm is not None:
                dt = now - self._last_now
                # Beats elapsed = time * beats-per-second. beats-per-second is
                # bpm/60 (bpm is beats per MINUTE).
                beats_elapsed = dt * accepted_bpm / 60.0
                # Compare total phase then (count + distance) to phase now to get
                # how many integer beat lines we crossed. We reconstruct it from
                # elapsed time because that's robust to the exact distance values.
                whole_beats = int(
                    self._last_beat_distance + beats_elapsed - beat_distance + 0.5
                )
                if whole_beats > 0:
                    self._beat_count += whole_beats
                elif wrapped:
                    # Fallback: elapsed-time math said "less than one beat" (e.g.
                    # tempo momentarily unknown a moment ago, or timing jitter),
                    # but the phase clearly wrapped high->low, so count the one
                    # beat we can plainly see.
                    self._beat_count += 1
            elif wrapped:
                # No trustworthy tempo yet, but the phase visibly wrapped: count
                # the single beat we can directly observe.
                self._beat_count += 1

        # 3) Store this sample as the new anchor.
        self._last_now = now
        self._last_beat_distance = beat_distance
        self._last_bpm = accepted_bpm
        self._last_playing = playing
        if playposition is not None:
            self._last_position = playposition
        self._initialised = True

    # -- Reading out the estimate -------------------------------------------

    def beat_now(self, now: float) -> float | None:
        """Best current estimate of the combined beat number at time `now`.

        Returns None if we've never been updated or don't know the tempo (there's
        nothing honest to say yet). Otherwise returns integer_beats + phase.
        """
        if not self._initialised or self._last_bpm is None:
            return None

        # PAUSED: the music isn't moving, so the beat position is frozen at
        # wherever it was on the last sample. Extrapolating a stopped deck forward
        # would invent motion that isn't happening.
        if not self._last_playing:
            return self._beat_count + (self._last_beat_distance or 0.0)

        # PLAYING: extrapolate the phase forward from the last anchor using the
        # tempo. This is the smoothing: even with no new sample, phase advances
        # linearly with wall-clock time, exactly as steady music does.
        dt = now - (self._last_now or now)
        phase = (self._last_beat_distance or 0.0) + dt * self._last_bpm / 60.0

        # The extrapolated phase can exceed 1.0 (we've coasted past one or more
        # beat lines since the last sample). Fold those whole beats out of the
        # fractional phase and into the integer count so the fractional part stays
        # in [0, 1). We do this locally without mutating self._beat_count, because
        # beat_now() is a read - the counter is only advanced by real samples in
        # update(), keeping this method free of side effects and safe to call as
        # often as we like.
        whole = int(phase)  # phase is >= 0 here, so int() truncates toward 0 correctly
        frac = phase - whole
        return self._beat_count + whole + frac

    def bpm(self) -> float | None:
        """The last accepted tempo, or None if we don't have a trustworthy one."""
        return self._last_bpm

    def playing(self) -> bool:
        """True if, as of the last sample, the deck was playing."""
        return self._last_playing

    def snapshot(self, now: float) -> DeckState:
        """Bundle the current estimate into a DeckState for the rest of the app."""
        return DeckState(
            playing=self._last_playing,
            bpm=self._last_bpm,
            beat=self.beat_now(now),
            raw_position=self._last_position,
        )


def format_status(states: dict[int, DeckState]) -> str:
    """Render decks as one compact, terminal-friendly status line.

    Example:
        D1 PLAY 128.0bpm beat  63.42  |  D2 STOP   --  beat   --

    Plain ASCII on purpose (PLAY/STOP, "--" for unknowns) - Windows terminals
    don't reliably render unicode play/pause glyphs, and this line is meant to be
    watched live while debugging Phase 1.
    """
    parts = []
    for deck_num in sorted(states):
        st = states[deck_num]
        play = "PLAY" if st.playing else "STOP"
        # Fixed widths keep the columns from jittering as numbers change length,
        # which makes a fast-updating live line far easier to read.
        bpm_txt = f"{st.bpm:6.1f}bpm" if st.bpm is not None else "   --    "
        beat_txt = f"{st.beat:8.2f}" if st.beat is not None else "     --"
        parts.append(f"D{deck_num} {play} {bpm_txt} beat {beat_txt}")
    return "  |  ".join(parts)
