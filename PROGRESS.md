# Robot DJ — V2 Progress & Plan

> **Purpose of this file:** the single place that says where V2 stands and what to do
> next. Read the "START HERE NEXT SESSION" block first. Last updated: **2026-07-28**.

---

## START HERE NEXT SESSION

**Where we are:** **Phase 1 AND Phase 2 are done.** Phase 3 (planner + simulator) is next.

Phase 2's analyzer (`brain/analyzer.py`) passes all 5 offline synthetic tests and has been
validated against 4 real files. bpm/beats/downbeats check out cleanly on all of them.
Section boundaries look musically plausible on every track tried so far:
- **Disclosure - She's Gone, Dance On** (full track, 3:47): 6 sections - a clean build
  (0.15→0.25→0.37 energy) over the first minute, a breakdown dip back to 0.15 at 0:59,
  a rise, then one long final section (1:27 to end) at moderate-high energy.
- **01 Losing It**, **01 One More Time**, **01 Fail-safe**: all three are, surprisingly,
  genuinely only 60 seconds of audio each (confirmed by inspecting the loaded waveform,
  not a loading bug - likely preview clips, unlike the Disclosure file which came from a
  YouTube "Visualizer" rip and is the full song). Each still produced a sensible energy
  shape (quiet→loud→quiet, or a steady build).

**Open item carried into Phase 3:** most of the test files in `C:\music` are 60s previews,
not full tracks. Phase 3's planner needs real material around an actual transition point,
so get full-length versions of whichever two songs you want the first transition routine
built from before relying on this for a real test.

If section boundaries ever look off on a new track, the tuning constants at the top of
`analyzer.py` (`BOUNDARY_ENERGY_RATIO`, `BOUNDARY_SPECTRAL_DISTANCE`, `BOUNDARY_WINDOW_BEATS`,
`PHRASE_BEATS`) are the first place to adjust.

**What Phase 2 built this session:**
- `brain/analyzer.py` - `analyze(path) -> {bpm, beats, downbeats, sections}`. Uses
  `librosa.beat.beat_track` for bpm/beats; assumes 4/4 and picks whichever of the 4
  possible beat-phases has the loudest average onset strength as "downbeat" (kick
  drums usually land on beat 1); sections are found by testing a candidate boundary
  every 32 beats (8 bars - the smaller of the two common EDM phrase lengths) and
  keeping only the ones that are a real change - a quiet candidate merges into its
  neighbor, which is how a real 16-bar phrase falls out without having to guess 32
  vs 64 up front. This replaces semantic section labels (verse/chorus, which barely
  apply to instrumental dance music) with something that matches how the genre is
  actually structured.
- **"Real change" is judged two ways** (either is enough): energy (RMS) jumping/
  dropping ≥40%, OR MFCC-based timbre distance exceeding a threshold. Energy alone
  caught an obvious drop on a synthetic click track but **under-fired on the real
  Disclosure track tested this session** - found only 1 boundary in a 226s song.
  Root cause: modern dance music is heavily compressed/limited, so overall loudness
  barely moves between sections even when the actual instrumentation changes
  completely. MFCC timbre distance was added to catch that. Getting it right took
  two real bugs, both fixed:
  1. MFCC coefficient 0 is essentially log-energy/loudness, and its magnitude so
     dominates the vector that it swamped cosine similarity to near-zero
     sensitivity - two windows 40% louder/quieter but otherwise identical in timbre
     came out ~200x LESS different with it in than without. Fixed by dropping
     coefficient 0 before comparing (RMS already covers loudness separately).
  2. The synthetic test for this needed a CONTINUOUS added tone, not another short
     click - a ~30ms transient inside a mostly-silent beat interval doesn't move an
     8-beat mean-MFCC average enough to be measurable, and a loud-enough second
     click confused the beat tracker entirely. A quiet sustained tone (simulating a
     new instrument/pad/hi-hat loop entering) fixed both problems.
  3. `BOUNDARY_SPECTRAL_DISTANCE` had to be recalibrated against the real track:
     synthetic testing suggested ~0.08, but real distances on a full mix sit at a
     much smaller scale (~0.0003-0.022 measured) since a complex mix's spectral
     envelope barely shifts when one new element enters, compared to an isolated
     synthetic tone. Set to 0.015 based on a visible gap in that track's numbers -
     expect to retune as more real tracks get tested.
  - Result on the Disclosure track: went from 1 detected section to 6, including a
    clear quiet dip (energy 0.15) right after the loudest stretch (energy 0.37) -
    consistent with a buildup-into-breakdown moment.
- `brain/test_analyzer.py` - proves the math offline with a synthetic numpy "click
  track" (no real song needed), same philosophy as `test_phase_lock.py`. Currently
  passes 5/5. Also caught two earlier bugs, both fixed:
  1. Candidate section-boundary times must be computed analytically from bpm + the
     first downbeat, NOT by indexing a fixed beat-COUNT ahead into the detected
     `beats` array - the beat tracker can miss a handful of beats on sparse audio,
     and indexing by count compounds that miscount into a growing time error.
  2. A candidate boundary whose comparison window would run past the last real
     beat (into trailing tail/silence) reads as a fake energy drop - it's the
     track ending, not a structural change - so those candidates are now skipped.
- Tested against two real files: "Disclosure - She's Gone, Dance On" (bpm 133.9,
  472 beats, 6 sections after the spectral fix) and "01 Fail-safe" (bpm 139.7 - note
  this file is genuinely only 60 seconds of audio, confirmed by inspecting its
  loaded waveform, not a loading bug).
- Added `librosa` to `brain/requirements.txt` (already installed in the venv).

Positions are expressed in beats-since-track-start, the same unit `phase_lock.py` uses
for the live feed - so the planner (Phase 3) can eventually compare "the analyzer says
the drop is at beat 128" against "PhaseLock says we're live at beat 127.3" directly.

What changed the session before this (see "Key decisions" for the why, kept for context):
- Ran the clean, lag-free rate check from the prior session's open question (pause/play/pause
  on deck 1, reading Mixxx time + the feed's `beat` value at each pause).
- Readings: `T1 = 0:00.02`, `B1 = 1.00`; `T2 = 0:27.12`, `B2 = 41.65`; `bpm = 90.0`.
- Check: `ΔT = 27.10s`, `ΔB = 40.65`. Expected `ΔB = ΔT × (bpm/60) = 27.10 × 1.5 = 40.65` —
  **exact match.** The beat number advances at precisely the reported BPM rate, no drift.
- This confirms `midi_cc_feed.py` + `phase_lock.py` are correct and ready to build on.

**Your immediate next action:** start Phase 2 — the analyzer. It needs to take a song and
produce `{bpm, beats, downbeats, sections}` JSON (see Phases table). This is pure offline
audio analysis, no Mixxx/MIDI/arm needed to begin.

What changed the session before this (see "Key decisions" for the why, kept for context):
- The MIDI-clock path (`midi_feed.py`) is a **dead end** with this Mixxx: the stock
  "MIDI for light" preset sends VU meters + MTC timecode + a per-beat note, but **no MIDI
  clock and no continuous beat phase**. Confirmed by dumping the raw MIDI.
- So we built our **own Mixxx output mapping** (`brain/mixxx_mapping/RobotDJ_BeatFeed*`)
  that sends `beat_distance` (14-bit), `bpm`, and `play` per deck as MIDI CC, plus a Python
  decoder (`brain/midi_cc_feed.py`) that feeds the same tested `phase_lock.py`. This is the
  MIDI equivalent of the OSC feed, and it reports **both decks** independently.
- On the machine it runs: deck flips to `PLAY`, `bpm` is correct, `beat` climbs, both decks
  report. loopMIDI port here is named `MixxBeat 0` (note: one `x`).

---

## The V2 objective

Pick two songs → analyze each (BPM / beats / sections) → generate a transition routine →
execute it on the robot. The robot (a MECA500 arm) physically plays a **Pioneer DDJ-FLX4**
controller. The tracks live in DJ software; the robot pushes the real buttons/faders/knobs.

## The core problem V2 must solve

V1 ran the arm off a **blind wall-clock script**, so it never knew what beat the song was
actually at and drifted **more than a couple beats off**. That drift has four causes:
1. no known audio-start reference, 2. no re-sync (error accumulates), 3. the arm can't
always keep up, 4. no anticipation of the arm's own movement time.

## The fix (the shape of the whole design)

- **Awareness (feedback):** read the *live* playback position from the DJ software so the
  robot always knows the true beat. Kills causes 1 & 2. → This is Phase 1.
- **Anticipation (feedforward):** fire each physical command *early* by that action's
  measured latency, so the physical effect lands on the beat. Kills cause 4.
- **Arm-aware planning:** never schedule two moves closer than the arm can travel. Kills cause 3.
- **Plan offline, before the robot.** Planning stays fully offline; awareness only changes
  execution *timing*.
- **One routine, two backends:** the same beat-relative "routine" runs either in a
  **simulator** (drive Mixxx digitally, *hear* the mix, no arm — so we validate musicality
  before risking the arm) or on the **arm**.

## Key decisions & findings (so we don't re-litigate them)

- **Audio moved from Serato → Mixxx.** Reason: Serato exposes no live playback position;
  Mixxx does. Confirmed FLX4 ↔ Mixxx are compatible. Serato is retired for this project.
- **Stock Mixxx (Windows installer) has NO OSC option** — OSC is a compile-time feature not
  in the standard build. So we use the **MIDI path**: loopMIDI virtual port + a Mixxx output
  mapping → a Python feed. (The `live_feed.py` OSC path is kept in case a future/custom build
  has OSC.)
- **"MIDI for light" does NOT send MIDI clock** (found 2026-07-23 by dumping raw MIDI). It
  emits VU-meter notes, an MTC timecode sysex, a per-beat `beat_active` note (note 50) and a
  BPM note (note 52) — but no `0xF8` clock and no continuous beat phase. So `midi_feed.py`
  (clock reconstruction) can never lock with it, and `beat_active` alone is the ~50 ms-coarse
  signal we already decided not to trust. **`midi_feed.py` is therefore shelved.**
- **We wrote our own Mixxx output mapping instead** (`brain/mixxx_mapping/RobotDJ_BeatFeed*`):
  a timer (~30 ms) reads `beat_distance` (sent 14-bit for sub-beat precision), `bpm`
  (as `bpm-50`), and `play` for decks 1 & 2 and sends them as MIDI CC (deck 1 = CC 20–23,
  deck 2 = CC 24–27, channel 1). `brain/midi_cc_feed.py` decodes these into the existing
  `phase_lock.py`. This is the MIDI twin of the OSC feed — same data, and (unlike MIDI clock)
  **deck-aware**, reporting both decks independently.
- **FLX4 vs virtual port are opposite directions** and both are used eventually: FLX4 =
  input *into* Mixxx (how the robot drives the mix, Phase 4/5); loopMIDI = output *out of*
  Mixxx (how Python sees the beat, Phase 1). The FLX4 can't replace the virtual port.
- **No jog wheels** in V2 (too hard/timing-critical). Faders, knobs, buttons only.
- `song_script.json` is already the clean **brain↔body interface** — the planner generates it.

## Phases

| # | Phase | What it delivers | Status |
|---|-------|------------------|--------|
| 0 | Setup | Branch, Mixxx installed, FLX4↔Mixxx, brain/ env | ✅ done (FLX4 check deferred — not on hand) |
| 1 | **Live feed** | Python reads Mixxx's live beat/position (the drift fix's foundation) | ✅ done — gate confirmed (rate matches BPM exactly, see top) |
| 2 | Analyzer | `analyze(song) → {bpm, beats, downbeats, sections}` JSON | ✅ done — validated on 4 real files, sections musically plausible (see top) |
| 3 | Planner + Simulator | Generate a transition routine and **hear it in Mixxx**, no arm | ⬜ |
| 4 | Teach controls | Teach the arm the crossfader, channel faders, EQ/filter knobs, play/cue/SYNC buttons (no jog) | ⬜ physical |
| 5 | Arm backend | Run the validated routine on the arm, timed by the live feed + per-action lead times | ⬜ |

**Critical path:** Phase 1's gate is confirmed. Phases 2–3 (brain + simulator) need no arm.
Phase 4 (teaching) can happen in parallel at the hardware. Phase 5 joins the two proven halves.

## Repo layout & conventions

- **Working branch:** `feature/v2-mixxx-brain` (branched from `main`; PR back to `main`).
- `hardware/software/` = the robot **body** (V1, MECA arm control) — reused, do not disturb.
- `brain/` = the V2 **brain** (music listening, analysis, planning, simulation) — new work.
- New Python deps for the brain live in `brain/requirements.txt` (separate from the body's).
- Conventions: branch from `main`; give the user git commands to run rather than committing
  for them; no hardcoded values / no editing env files; minimal changes only.

## `brain/` file map (Phase 1 + 2)

- `analyzer.py` — Phase 2 core: `analyze(path) -> {bpm, beats, downbeats, sections}`.
  See "START HERE" above for how it works and its tuning constants.
- `test_analyzer.py` — offline proof via a synthetic click track (no real song needed).
  Run: `python test_analyzer.py`. Currently passes 5/5.

- `phase_lock.py` — core math: turns Mixxx's intermittent updates into a smooth live beat
  number. Standard-library only. **The correctness-critical piece.**
- `test_phase_lock.py` — offline proof of the math (no Mixxx/hardware). Run:
  `python test_phase_lock.py`. Currently passes 21/21.
- `midi_cc_feed.py` — **the feed we're using**: decodes our custom "Robot DJ Beat Feed"
  mapping's CC messages (beat_distance/bpm/play, both decks) via loopMIDI into `phase_lock`.
- `mixxx_mapping/RobotDJ_BeatFeed.midi.xml` + `RobotDJ_BeatFeed-scripts.js` — the custom
  Mixxx **output mapping** that emits those CCs. **Install:** copy both into
  `%LOCALAPPDATA%\Mixxx\controllers\` (`Copy-Item C:\robot-dj\brain\mixxx_mapping\RobotDJ_BeatFeed* "$env:LOCALAPPDATA\Mixxx\controllers\"`),
  restart Mixxx, then load "Robot DJ Beat Feed" on the loopMIDI port. CC layout is documented
  at the top of both files and must stay in sync between them.
- `midi_feed.py` — SHELVED MIDI-clock feed. Kept for reference, but "MIDI for light" sends no
  clock (see Key decisions), so it can't be used with this Mixxx.
- `live_feed.py` — OSC feed (unused for now; needs an OSC-enabled Mixxx build). Has a
  `--discovery` mode and a single `parse_address()` function to tune if OSC ever comes online.
- `SETUP_MIXXX_FEED.md` — full Windows setup for both feed options + troubleshooting.
- `requirements.txt`, `README.md` — deps and folder orientation.

## What's NOT built yet

- Phase 3 planner + simulator, Phase 4 new taught controls (crossfader still not taught),
  Phase 5 feedback-driven arm executor.
- Real per-action arm latencies and the planner's arm travel-time table (measured in Phase 5).
- Knob `degrees_per_unit` is still a placeholder in `hardware/software/controls.json`.
