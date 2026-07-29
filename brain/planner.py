"""Phase 3 (planner half): turn two analyzed songs + a chosen transition point into a
beat-relative "routine" - what to do, and when, to mix from song A into song B.

WHERE THIS FITS
---------------
analyzer.py (Phase 2) tells us WHERE the beats/bars/sections are in each song, offline.
This module decides WHAT TO DO with that information for one specific transition, still
entirely offline - it produces a plan, not an action. simulator.py (the other Phase 3
half) is what actually executes a routine, live, by watching Phase 1's real-time beat
feed and sending MIDI into Mixxx accordingly.

v1 SCOPE, ON PURPOSE
---------------------
- Crossfader + volume only - no EQ swaps yet. Proves the whole pipeline (plan -> MIDI ->
  Mixxx -> audible mix) before adding musical sophistication on top.
- YOU choose the transition point (which beat of song A to start on, which beat of song B
  to enter from - typically a section boundary from analyzer.py) - the planner does not
  judge which songs/sections sound good together. That is a harder, separate problem.
- Song B's entry point is a Mixxx HOT CUE, not a raw seek. The real MECA arm can only
  press a physical button, never jump to an arbitrary sample position - so the simulator
  has to work the same way the arm eventually will: you set a hot cue at song B's entry
  point in Mixxx beforehand, and the routine just tells the simulator (or, later, the arm)
  to press it. Keeping this constraint even in software is what makes the simulator a
  meaningful preview of what the arm can actually do, not just a more capable stand-in.
- The two songs are assumed already tempo-matched (e.g. via Mixxx's own SYNC) close enough
  that "N beats of A" and "N beats of B" take the same wall-clock time once both are
  playing - plan_transition() checks this and refuses to plan a mix across mismatched
  tempos rather than silently producing a routine that will drift.
"""

# How far apart two songs' bpm can be and still be considered "tempo-matched" for a
# crossfade. Real DJ tempo-matching (e.g. Mixxx's SYNC) gets far closer than this; this
# is a sanity ceiling to catch "these two songs were never synced" mistakes, not a
# tolerance you should expect to actually approach.
MAX_BPM_MISMATCH_FRACTION = 0.03


def plan_transition(
    song_a: dict,
    song_b: dict,
    start_beat_a: int,
    entry_beat_b: int = 0,
    crossfade_beats: int = 32,
    hotcue_b: int = 1,
) -> dict:
    """Build a transition routine from song A (beat `start_beat_a` onward) into song B
    (entered at its hot cue `hotcue_b`, pre-set at beat `entry_beat_b`).

    `song_a`/`song_b` are analyzer.analyze() output dicts (or equivalent - only "bpm" and
    "beats" are used). Raises ValueError if the request doesn't make sense: an
    out-of-range beat, a crossfade that would run past the end of song A, or bpms too far
    apart to treat as tempo-matched (see MAX_BPM_MISMATCH_FRACTION).
    """
    beats_a, beats_b = song_a["beats"], song_b["beats"]
    bpm_a, bpm_b = song_a["bpm"], song_b["bpm"]

    if not (0 <= start_beat_a < len(beats_a)):
        raise ValueError(
            f"start_beat_a={start_beat_a} is out of range for song A "
            f"({len(beats_a)} beats detected)"
        )
    if not (0 <= entry_beat_b < len(beats_b)):
        raise ValueError(
            f"entry_beat_b={entry_beat_b} is out of range for song B "
            f"({len(beats_b)} beats detected)"
        )
    end_beat_a = start_beat_a + crossfade_beats
    if end_beat_a >= len(beats_a):
        raise ValueError(
            f"crossfade_beats={crossfade_beats} starting at beat {start_beat_a} runs "
            f"past song A's last detected beat ({len(beats_a) - 1}) - pick an earlier "
            f"start_beat_a or a shorter crossfade"
        )

    bpm_mismatch = abs(bpm_a - bpm_b) / bpm_a
    if bpm_mismatch > MAX_BPM_MISMATCH_FRACTION:
        raise ValueError(
            f"song A ({bpm_a:.1f} bpm) and song B ({bpm_b:.1f} bpm) differ by "
            f"{bpm_mismatch:.1%}, more than the {MAX_BPM_MISMATCH_FRACTION:.0%} treated "
            f"as tempo-matched - enable Mixxx's SYNC (or otherwise tempo-match the "
            f"decks) before mixing these two, or choose closer-tempo tracks"
        )

    return {
        "song_a": {
            "bpm": bpm_a,
            "start_beat": start_beat_a,
            "start_time": beats_a[start_beat_a],
        },
        "song_b": {
            "bpm": bpm_b,
            "entry_beat": entry_beat_b,
            "entry_time": beats_b[entry_beat_b],
            "hotcue": hotcue_b,
        },
        "crossfade_beats": crossfade_beats,
        # Crossfader position over time, in song A's beat count (the shared clock once
        # tempo-matched): 0.0 = full A, 1.0 = full B. The simulator linearly interpolates
        # between these using the LIVE beat number from Phase 1, not wall-clock time.
        "crossfader_keyframes": [
            {"beat": start_beat_a, "position": 0.0},
            {"beat": end_beat_a, "position": 1.0},
        ],
        # When song A's live beat crosses this, trigger song B's hot cue (which both
        # seeks to entry_beat_b AND starts playback, in one press - exactly what a
        # single button-press does on the real controller).
        "trigger_song_b_at_beat": start_beat_a,
    }
