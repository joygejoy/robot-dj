"""Phase 2: turn a song FILE into a JSON-able map of its musical structure.

WHERE THIS FITS
---------------
Phase 1 (phase_lock.py + midi_cc_feed.py) answers "what beat is playing RIGHT NOW,
live?" This module answers a different question, entirely offline, before the robot
ever touches anything: "where are the beats, bars, and structural boundaries in this
song, in advance?" The planner (Phase 3) reads this output to decide WHEN to schedule
each transition action; Phase 1 then keeps that plan in sync with the real playback.

Both modules describe position the same way - beats since track start - so the
planner can eventually compare "the analyzer says the drop is at beat 128" against
"PhaseLock says we're live at beat 127.3" using one shared unit.

WHY DOWNBEATS AND SECTIONS ARE HEURISTICS, NOT EXACT ANSWERS
--------------------------------------------------------------
- We ASSUME every track is 4/4. librosa gives us beats, not which beat is "1" of the
  bar - we recover that by picking whichever of the 4 possible phases has the loudest
  average onset strength (kick drums usually land on beat 1).
- Rather than classify sections semantically (verse/chorus/etc, which barely applies
  to instrumental dance music), we lean on how EDM is actually structured: built in
  repeating 8-bar (32-beat) phrases, with real structural changes landing ON a phrase
  boundary. So we test a candidate boundary every 32 beats and keep only the ones
  that are a real change - a quiet candidate merges into its neighbor, which is how
  a real 16-bar (64-beat) phrase naturally falls out without having to guess 32 vs
  64 up front.
- "Real change" is judged two ways, either one is enough: energy (RMS) jumping or
  dropping, OR the timbre/spectral content (MFCC) shifting. Energy alone caught an
  obvious drop/breakdown on a synthetic click track, but under-fired on a real,
  commercially mastered song - modern dance music is heavily compressed, so overall
  loudness barely moves across sections even when the actual instrumentation
  changes completely (new bassline, hi-hats dropping out, a filter sweep). MFCC
  distance catches that content change directly; energy still catches genuine
  loudness-only moments (like a drum break-out) that MFCC might undersell.
"""
import numpy as np
import librosa


# --- Tuning constants (see phase_lock.py for why these live here, not buried) ---

# Candidate section-boundary spacing: 8 bars * 4 beats/bar, in 4/4. This is the
# SMALLER of the two common EDM phrase lengths (8 or 16 bars) on purpose - a real
# 16-bar phrase just merges two adjacent 32-beat candidates that show no change
# between them (see BOUNDARY_ENERGY_RATIO below), so we never have to guess which
# one a given track uses.
PHRASE_BEATS = 32
PHRASE_BARS = PHRASE_BEATS // 4

# How many beats of audio to average on each side of a candidate boundary when
# deciding whether it's a real structural change. Short enough to be local to the
# boundary, long enough to smooth out single-beat energy jitter.
BOUNDARY_WINDOW_BEATS = 8

# A candidate boundary counts as "real" if energy after / energy before (or its
# reciprocal) exceeds this ratio - i.e. energy changed by at least 40%. Below this,
# we treat it as the same section continuing and merge across it.
BOUNDARY_ENERGY_RATIO = 1.4

# How many MFCC coefficients to compute. 13 is the standard default for timbre
# comparison (enough to capture the coarse spectral shape - which instruments/
# frequency bands are present - without chasing fine pitch detail we don't need).
# Coefficient 0 is dropped before comparing (see _find_sections): it's essentially
# log-energy/loudness, which the RMS check already covers separately, and its
# magnitude is so much larger than the shape coefficients (1..12) that leaving it
# in swamps cosine similarity - two windows that are 40% louder/quieter but
# otherwise identical in timbre came out ~200x LESS different with it in than
# without, which silently made the whole spectral check nearly blind.
MFCC_COUNT = 13

# A candidate boundary also counts as "real" if the cosine distance between the
# mean MFCC vector before and after exceeds this. Cosine distance is 0 for
# identical timbre and grows toward 1 as the spectral "shape" diverges.
#
# Picked empirically against a real track (Disclosure - She's Gone, Dance On),
# NOT from the synthetic test - real, fully-produced music sits at a much smaller
# scale than an isolated synthetic tone does (measured distances ranged ~0.0003 to
# ~0.022 across the whole song, vs ~0.16+ for a synthetic added tone), because a
# full mix's spectral envelope is already broad and complex, so one new element
# moves the average far less. There was a visible gap in that track's numbers
# between a "noise" cluster (<0.01) and a "real change" cluster (>0.013) - this
# sits between them. Expect to retune as more real tracks get tested.
BOUNDARY_SPECTRAL_DISTANCE = 0.015

# Guard against divide-by-zero when a window is near-silent, or against a
# zero-vector MFCC window (e.g. true digital silence) breaking cosine distance.
_ENERGY_EPS = 1e-6
_VECTOR_EPS = 1e-9


def analyze(path: str) -> dict:
    """Load an audio file and analyze it. Thin wrapper around analyze_signal() so
    the correctness-critical logic can be unit-tested on synthetic in-memory audio
    (see test_analyzer.py) without needing a real music file on disk."""
    y, sr = librosa.load(path, sr=None, mono=True)
    return analyze_signal(y, sr)


def analyze_signal(y: np.ndarray, sr: int) -> dict:
    """Core analysis: bpm, beat timestamps, downbeat timestamps, and phrase-based
    section boundaries, for one mono audio signal `y` at sample rate `sr`."""
    bpm, beats = _find_beats(y, sr)
    downbeat_phase, downbeat_beat_indices = _find_downbeat_phase(y, sr, beats)
    sections = _find_sections(y, sr, bpm, beats, downbeat_beat_indices)

    return {
        "bpm": bpm,
        "beats": beats.tolist(),
        "downbeats": beats[downbeat_beat_indices].tolist(),
        "sections": sections,
    }


def _find_beats(y: np.ndarray, sr: int) -> tuple[float, np.ndarray]:
    """Tempo + beat timestamps (seconds), via librosa's standard beat tracker."""
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    # librosa has returned tempo as either a bare float or a length-1 array across
    # versions; normalise to a plain float so callers/JSON don't have to care.
    bpm = float(np.atleast_1d(tempo)[0])
    beats = librosa.frames_to_time(beat_frames, sr=sr)
    return bpm, beats


def _find_downbeat_phase(
    y: np.ndarray, sr: int, beats: np.ndarray
) -> tuple[int, np.ndarray]:
    """Which of the 4 possible beat-phases is "beat 1" of the bar, assuming 4/4.

    Returns (phase, beat_indices) where beat_indices are the positions in `beats`
    that are downbeats (i.e. range(phase, len(beats), 4)).
    """
    if len(beats) < 4:
        # Too short to judge a 4-beat phase; call the first beat the downbeat.
        return 0, np.arange(0, len(beats), 4)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    beat_frames = librosa.time_to_frames(beats, sr=sr)
    # Clip: rounding can push the last beat's frame one past the envelope's end.
    beat_frames = np.clip(beat_frames, 0, len(onset_env) - 1)
    onset_at_beats = onset_env[beat_frames]

    # Kick drums (and most percussive emphasis) land on beat 1 far more than on
    # beats 2-4, so the phase with the highest average onset strength wins.
    phase_scores = [onset_at_beats[phase::4].mean() for phase in range(4)]
    phase = int(np.argmax(phase_scores))

    return phase, np.arange(phase, len(beats), 4)


def _find_sections(
    y: np.ndarray,
    sr: int,
    bpm: float,
    beats: np.ndarray,
    downbeat_beat_indices: np.ndarray,
) -> list[dict]:
    """Phrase-grid section boundaries: test every 32-beat candidate, keep the ones
    where energy actually changes, merge the ones where it doesn't.

    Candidate boundary TIMES are computed analytically from bpm + the first
    downbeat, not by indexing PHRASE_BARS-many-downbeats-ahead into the detected
    `beats` array. The beat tracker can occasionally miss a handful of beats on a
    sparse/percussive signal, and indexing ahead by a fixed COUNT compounds that
    miscount into a growing time error the further into the track you go. Deriving
    the time directly from the (assumed-steady) tempo sidesteps that entirely -
    we only use the detected beats afterwards, to label each boundary with its
    nearest real beat index for the JSON output.
    """
    rms = librosa.feature.rms(y=y)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    # [1:] drops coefficient 0 (log-energy) - see MFCC_COUNT's comment for why.
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=MFCC_COUNT)[1:]
    mfcc_times = librosa.frames_to_time(np.arange(mfcc.shape[1]), sr=sr)
    beat_seconds = 60.0 / bpm
    window_seconds = BOUNDARY_WINDOW_BEATS * beat_seconds
    track_end_time = float(rms_times[-1]) if len(rms_times) else float(beats[-1])

    def mean_energy(t_start: float, t_end: float) -> float:
        mask = (rms_times >= t_start) & (rms_times < t_end)
        return float(rms[mask].mean()) if mask.any() else 0.0

    def mean_mfcc(t_start: float, t_end: float) -> np.ndarray | None:
        mask = (mfcc_times >= t_start) & (mfcc_times < t_end)
        return mfcc[:, mask].mean(axis=1) if mask.any() else None

    def spectral_distance(before: np.ndarray | None, after: np.ndarray | None) -> float:
        """Cosine distance between two mean-MFCC vectors: 0 = identical timbre,
        growing toward 1 as spectral "shape" diverges."""
        if before is None or after is None:
            return 0.0
        denom = np.linalg.norm(before) * np.linalg.norm(after)
        if denom < _VECTOR_EPS:
            return 0.0
        cosine_similarity = float(np.dot(before, after) / denom)
        return 1.0 - cosine_similarity

    def nearest_beat_index(t: float) -> int:
        return int(np.argmin(np.abs(beats - t)))

    first_downbeat_time = (
        float(beats[downbeat_beat_indices[0]]) if len(downbeat_beat_indices) else 0.0
    )
    phrase_seconds = PHRASE_BEATS * beat_seconds
    # A candidate whose "after" window would run past the last real beat is
    # untestable - trailing silence/tail there isn't a structural change, it's
    # just the track ending, so don't offer it as a candidate at all.
    last_beat_time = float(beats[-1]) if len(beats) else track_end_time
    n_candidates = int((last_beat_time - window_seconds - first_downbeat_time) // phrase_seconds)

    confirmed_boundaries = [0]
    for k in range(1, n_candidates + 1):
        t = first_downbeat_time + k * phrase_seconds

        energy_before = mean_energy(t - window_seconds, t)
        energy_after = mean_energy(t, t + window_seconds)
        energy_ratio = energy_after / max(energy_before, _ENERGY_EPS)
        is_energy_change = (
            energy_ratio >= BOUNDARY_ENERGY_RATIO
            or energy_ratio <= 1.0 / BOUNDARY_ENERGY_RATIO
        )

        mfcc_before = mean_mfcc(t - window_seconds, t)
        mfcc_after = mean_mfcc(t, t + window_seconds)
        is_spectral_change = (
            spectral_distance(mfcc_before, mfcc_after) >= BOUNDARY_SPECTRAL_DISTANCE
        )

        if is_energy_change or is_spectral_change:
            confirmed_boundaries.append(nearest_beat_index(t))
    confirmed_boundaries.append(len(beats))

    sections = []
    for start_idx, end_idx in zip(confirmed_boundaries, confirmed_boundaries[1:]):
        start_time = float(beats[start_idx]) if start_idx < len(beats) else track_end_time
        end_time = float(beats[end_idx]) if end_idx < len(beats) else track_end_time
        sections.append(
            {
                "start_beat": start_idx,
                "end_beat": end_idx,
                "start_time": start_time,
                "end_time": end_time,
                "energy": mean_energy(start_time, end_time),
            }
        )
    return sections
