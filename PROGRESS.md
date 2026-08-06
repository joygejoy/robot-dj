# Robot DJ — V2 Progress & Plan

> **Purpose of this file:** the single place that says where V2 stands and what to do
> next. Read the "START HERE NEXT SESSION" block first. Last updated: **2026-08-05**.

---

## START HERE NEXT SESSION

**Where we are: Phase 4 (teach controls) is partially done.** Taught and wired this
session: the **crossfader** (both endpoints + hovers, registered in `controls.json` as
a `slider` control for `move_slider()`), the **left channel fader** (`left_volume_top`/
`_75`/`_half` + hovers, same directly-taught convention as `right_volume` - no
`controls.json` entry needed), and three of four **cue/sync buttons**
(`right_cue_press`, `left_cue_press`, `left_sync_press` + hovers). All of these are
wired into `meca_controller.py`'s `HOVER_FOR` and (for the buttons) `test_actions.py`'s
`BUTTONS` dict, so each can be smoke-tested individually:
```powershell
python test_actions.py move-to <position_name>       # e.g. left_volume_top - hover only, no dive
python test_actions.py press-button <right_cue|left_cue|left_sync>
```

**Deliberately skipped this session:** the remaining EQ/filter knobs (`left_mid`,
`right_filter`, `right_eq_hi`, `left_eq_hi`, `right_eq_low`, `left_eq_low`) - not
blocking anything the planner currently uses (it only ever emits crossfader + hotcue
actions), so teaching them was deferred rather than done. Revisit whenever a
choreography actually needs EQ moves.

**Blocked, not a bug: `right_sync_press` could not be taught.** Confirmed with the
user - the gripper cannot physically reach the right deck's SYNC button (mechanical
interference at that spot on the board). Not a software problem; would need a
different approach angle or a fixture change to revisit. Left untaught.

**This unblocks Phase 5's first real target:** the crossfader is now taught, so the
Disclosure -> ANOTR routine validated live in Mixxx during the Phase 3 session could,
in principle, be attempted on the real arm next - but Phase 5 (the feedback-driven arm
executor that reads the live beat and drives `meca_controller` instead of the
simulator's MIDI output) hasn't been built yet. Teaching is necessary but not
sufficient on its own.

**Several real bugs were found and fixed in the teaching tools this session** (not in
the brain/analysis code - these are all in `hardware/software/`):
1. **`derive_position.py` caused a real collision** (crashed into a knob). Its
   non-reference branch did ONE compound `MoveLin` from `safe_hover` - whose own
   Cartesian pose was never taught/verified (`pose: null` in `positions.json`) -
   straight to a newly-computed working-depth target, changing X/Y/Z/orientation all
   at once. If `safe_hover`'s real depth was closer to the board than assumed, the
   whole path stayed too close the entire time. **Fixed** by splitting it into the
   same retract/cross/dive shape `meca_controller.move_to()` already uses for known
   positions: (1) a pure X-only move to the imported `SAFE_X` constant, (2) a
   `MoveLin` crossing Y/Z/orientation to match the target while still held at
   `SAFE_X`, (3) a final pure-X dive to the target's actual depth (safe because Y/Z/
   orientation already match by that point). `derive_position.py` now imports
   `SAFE_X` from `meca_controller` instead of a second hardcoded `175`.
2. **Even with that fix, a freshly-computed `MoveLin` target can still legitimately
   fail** - `MX_ST_OUT_OF_REACH` (hit deriving `crossfader_left_hover`) and
   `MX_ST_SINGULARITY_ERR` (hit deriving `left_volume_top_hover` - likely because
   `left_volume`'s Y≈-30 sits close enough to the arm's centerline for that
   orientation to create a wrist singularity, unlike `right_volume`'s Y≈-75). Both
   are genuine kinematic limits, not code bugs - and both times the robot refused the
   move cleanly with no collision. The fix each time was to abandon
   `derive_position.py` for that one hover and just physically jog + `teach.py` it
   directly instead. **Takeaway: if `derive_position.py` faults on a brand-new area of
   the workspace, don't retry the math - just teach the hover directly.**
3. **`test_actions.py`'s `cmd_move_to` had a latent safety-check bug that caused a
   second real collision** (drove into the board). `HOVER_FOR.get(name, name)`
   silently falls back to the position's own name whenever no hover is registered for
   it - which trivially passes the "target in mc.positions" check whenever the working
   position itself is already taught (which it always is, by definition, once you've
   run `teach.py` on it). This let `python test_actions.py move-to left_volume_top`
   slip through and do a raw `MoveJoints` straight into the board, because
   `left_volume_top_hover` hadn't been added to `HOVER_FOR` yet at that point. **Fixed:**
   `cmd_move_to` now requires either an explicit `HOVER_FOR` entry, or that `name` is
   itself already a hover/reference position (ends with `_hover`, or is `home`/
   `safe_hover`) - anything else is rejected with a clear error instead of silently
   "working."
4. **New standing procedural rule (can't be fixed in code):** reconnecting to the robot
   (`derive_position.py`, `test_actions.py`, `runner.py` - anything through
   `MecaController`/`Robot()`) always calls the robot's own factory `Home()` routine
   first, which has zero awareness of the external DJ controller board. Starting that
   from an engaged/deep position can crash into the board, and this can't be checked in
   code - pose reads aren't meaningful before homing completes. **Always manually
   retract the gripper to a board-clear pose via the web UI before running any script
   that reconnects.**
5. **Two teaching mistakes, caught by comparing recorded numbers before trusting
   them (not code bugs):** `left_volume_top` was first saved as an exact duplicate of
   `crossfader_right_hover` (the gripper hadn't actually moved before `teach.py` ran) -
   caught by comparing pose values, re-taught. Its second teach also landed ~15mm too
   high in Z vs. `right_volume_top`'s reference height (89.15 vs 87.965 the second
   time - much closer) - re-taught again. **Takeaway: sanity-check a newly-taught
   pose's numbers against an analogous already-taught one before deriving anything
   from it.**

**Known minor imprecision, left as-is by user's choice:** `left_volume_75`/
`left_volume_half`'s X/Y (207.52, -33.575) differs from `left_volume_top`'s (206.245,
-30.3) by a few mm - on `right_volume`, all three stops share identical X/Y (it's a
single-axis mechanical slide, so gripping the same track should land on the same X/Y
regardless of height). Not expected to be dangerous, just possibly a slightly less
solid grip on `left_volume_top` specifically.

**Repo state - nothing committed yet:** `hardware/software/{controls.json,
derive_position.py, meca_controller.py, positions.json, test_actions.py}` are all
modified. `brain/_analysis_a.json`, `brain/_analysis_b.json`, `brain/routine.json` are
untracked leftovers from the Phase 3 live validation run. Commit when ready - see repo
layout & conventions below for the branch/PR convention (branch from `main`, don't
commit for the user).

**Next up:** either finish Phase 4 (teach the deferred EQ/filter knobs, or take another
run at `right_sync_press` with a different approach angle) or move to Phase 5 (build
the feedback-driven arm executor - the actual next milestone now that the crossfader
exists).

---

### Phase 3 — live validation run (previous session, kept for detail)

**Where we are: Phase 3 is fully validated end-to-end against live Mixxx.** Two
full-length, tempo-matched tracks - **Disclosure - She's Gone, Dance On** (133.9 bpm) into
**ANOTR ft. 54 Ultra - Talk To You** (130.8 bpm, 2.3% mismatch, under the 3% ceiling) - were
analyzed, planned (crossfade starting at song A beat 195 / ~87.5s, 32 beats / 8 bars long,
entering song B at its hot cue 1 set at beat 0), and run live: the simulator tracked deck
1's real beat via the Phase 1 feed, and when it crossed beat 195 it faded the crossfader
from full-A to full-B over 32 beats and fired deck 2's hot cue at the right moment. **Heard
and confirmed working by ear.** This is the first real proof the whole brain pipeline
(analyze → plan → watch live beat → drive Mixxx) works, not just offline math.

**Next up: Phase 4 (teach controls)** - the crossfader, channel faders, EQ/filter knobs,
and play/cue/SYNC buttons need to be physically taught to the MECA500 arm on the real
DDJ-FLX4. This is hardware work, no brain code needed, and can happen independently of
anything else. See the Phases table below for what Phase 4 covers.

**Two things fixed along the way this session, worth knowing about:**
- `mixxx_mapping/RobotDJ_SimInput.midi.xml` failed to load with `Expected '>', but got
  '-'. at line 17, column 5` - the file's own comment block used `----` dashed lines as a
  table separator, but XML forbids a literal `--` anywhere inside a comment. Fixed by
  swapping those separator lines to `====`. Watch for this if any other mapping file's
  comments ever get a dashed-line separator added.
- **loopMIDI port names are not stable across sessions** - they were `MixxBeat 0` /
  `RobotDJSim 0` when originally set up, but after recreating ports this session they came
  back as `MixxBeat 1` / `RobotDJSim 2` (loopMIDI increments a counter rather than reusing
  index 0). **Don't hardcode the trailing number** - before running anything that opens a
  port by name, check the live list first:
  ```powershell
  python -c "import mido; print(mido.get_output_names())"
  ```
  and use whatever full names come back.

**A third thing worth knowing, hit during the live run:** if Mixxx has no audio, check
**Preferences → Sound Hardware** before suspecting the MIDI pipeline. Two real issues hit
this session, neither related to the brain code:
- **Realtek ASIO failed with "unanticipated host error"** - consumer Realtek chips'
  bundled ASIO driver is often flaky/exclusive-access-only. Fix: switch the Sound Hardware
  **API** dropdown from ASIO to **WASAPI** (or DirectSound if WASAPI misbehaves) - a plain
  playback test doesn't need ASIO's low latency.
- **"invalid sampling rate"** after switching to WASAPI - Mixxx's **Sample Rate** setting
  didn't match Windows' configured default format for the device. Fix: Windows Sound
  Settings → Playback → device → Properties → Advanced tab → note the **Default Format**
  (e.g. "16 bit, 44100 Hz"), then set Mixxx's Sample Rate to match exactly.

**The exact commands used for the validated run** (kept as a template for the next
transition - remember port names and beat numbers will differ next time):
```powershell
python -c "import mido; print(mido.get_output_names()); print(mido.get_input_names())"  # confirm current port names first - they drift across sessions, see above
python -c "
import json, analyzer, planner
a = analyzer.analyze(r'C:/music/Disclosure - She's Gone, Dance On (Visualizer).mp3')
b = analyzer.analyze(r'C:/music/ANOTR ft. 54 Ultra - Talk To You [No Art].mp3')
r = planner.plan_transition(a, b, start_beat_a=195, entry_beat_b=0, crossfade_beats=32, hotcue_b=1)
json.dump(r, open('routine.json', 'w'), indent=2)
"
python simulator.py --routine routine.json --beat-feed-port "MixxBeat 0" --sim-port "RobotDJSim 2" --song-a-deck 1 --song-b-deck 2
```
Note the beat-feed port came from `get_input_names()` (simulator reads it as MIDI input)
while the sim port came from `get_output_names()` (simulator writes to it as MIDI output) -
loopMIDI gives each virtual port's two directions different trailing numbers, so don't
assume they match.

**What Phase 3 built this session:**
- `brain/planner.py` - `plan_transition(song_a, song_b, start_beat_a, entry_beat_b,
  crossfade_beats, hotcue_b) -> routine`. Takes two analyzer.py outputs plus your chosen
  transition point, returns a beat-relative routine: crossfader keyframes (0.0 at the
  start beat, 1.0 `crossfade_beats` later) and the beat at which to trigger song B's hot
  cue. Refuses to plan (raises `ValueError` with a clear message) if: the requested beat
  is out of range, the crossfade would run past song A's last detected beat, or the two
  songs' bpms differ by more than 3% (assumed tempo-matched via Mixxx's own SYNC - a
  mismatch this large means the decks were never actually synced, so the routine would
  drift rather than proceed as blind wall-clock timing would hide).
- `brain/test_planner.py` - 5/5 passing, fully offline (fake bpm/beat-count dicts, no
  Mixxx/real songs needed): correct routine shape, and each of the three rejection cases
  above.
- `brain/mixxx_mapping/RobotDJ_SimInput.midi.xml` - the new Mixxx INPUT mapping (opposite
  direction from `RobotDJ_BeatFeed`, which is output-only). Purely declarative (no
  companion JS needed, unlike the beat feed - a plain CC/note passthrough doesn't need a
  polling timer): CC 0x10 → `[Master] crossfader`, note 0x00 → `[Channel1]
  hotcue_1_activate`, note 0x01 → `[Channel2] hotcue_1_activate`. **Installed, loaded, and
  proven live** - see "START HERE" above.
- `brain/simulator.py` - `run(routine, beat_feed_port, sim_port, song_a_deck,
  song_b_deck)`. Watches song A's LIVE beat over the existing Phase 1 feed (reuses
  `midi_cc_feed.CcBeatReader` directly rather than re-decoding CCs) and drives the
  crossfader + song B's hot cue accordingly - the same "awareness over blind timing"
  principle Phase 1 exists for, applied here instead of to the eventual arm. The
  interpolation math (`crossfader_value_at`, `to_midi_cc`) is split out into pure,
  fully-offline-testable functions, same pattern as `phase_lock.py` vs `midi_cc_feed.py`.
  **Proven live this session** - see "START HERE" above for the full validated run.
- `brain/test_simulator.py` - 7/7 passing, proves the interpolation math (holds before/
  after the fade, linear in between, correct MIDI byte conversion, clamps out-of-range
  input) without needing Mixxx or MIDI hardware.

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

**History (Phase 1, oldest first - kept for context, not action items):**
- Phase 1 gate check: pause/play/pause on deck 1, reading Mixxx time + the feed's `beat`
  value at each pause. Readings: `T1 = 0:00.02`, `B1 = 1.00`; `T2 = 0:27.12`, `B2 = 41.65`;
  `bpm = 90.0`. Check: `ΔT = 27.10s`, `ΔB = 40.65`. Expected `ΔB = ΔT × (bpm/60) = 27.10 ×
  1.5 = 40.65` — **exact match.** Confirmed `midi_cc_feed.py` + `phase_lock.py` are correct.
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
| 3 | Planner + Simulator | Generate a transition routine and **hear it in Mixxx**, no arm | ✅ done — full end-to-end run against live Mixxx with two real full-length tracks, heard and confirmed working (see top) |
| 4 | Teach controls | Teach the arm the crossfader, channel faders, EQ/filter knobs, play/cue/SYNC buttons (no jog) | 🟡 partially done — crossfader, left_volume, right/left_cue, left_sync taught; EQ/filter knobs deferred, right_sync unreachable (see START HERE) |
| 5 | Arm backend | Run the validated routine on the arm, timed by the live feed + per-action lead times | ⬜ |

**Critical path:** Phases 1–3 (the whole brain: live feed, analyzer, planner, simulator)
are done and validated. Phase 4 (teaching) is next, physical, and can happen independently
of any more brain work. Phase 5 joins the two proven halves.

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
- `planner.py` — Phase 3 core (planner half): `plan_transition(...) -> routine`.
  Beat-relative crossfade routine between two analyzed songs. No Mixxx needed to run.
- `test_planner.py` — offline proof with fake bpm/beat-count dicts. Run:
  `python test_planner.py`. Currently passes 5/5.
- `simulator.py` — Phase 3 core (simulator half): `run(routine, ...)`. Executes a routine
  live in Mixxx - watches song A's real beat over the existing Phase 1 feed, drives the
  crossfader + song B's hot cue over a NEW MIDI port. **Validated against live Mixxx.**
- `test_simulator.py` — offline proof of the interpolation math only (the live loop can't
  be unit-tested - needs real Mixxx). Run: `python test_simulator.py`. Passes 7/7.
- `mixxx_mapping/RobotDJ_SimInput.midi.xml` — the new Mixxx **input** mapping simulator.py
  sends to. Purely declarative, no companion JS needed. **Installed and loaded** on a
  SECOND loopMIDI port (separate from the beat-feed port) as "Robot DJ Sim Input" -
  MIDI smoke test confirmed the crossfader responds. Reinstall after any edit with:
  `Copy-Item C:\robot-dj\brain\mixxx_mapping\RobotDJ_SimInput.midi.xml "$env:LOCALAPPDATA\Mixxx\controllers\"`.
  Note: an earlier version failed to parse (`--` inside an XML comment is illegal) - fixed,
  see "START HERE" above.

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

- Phase 4 remainder: EQ/filter knobs (`left_mid`, `right_filter`, `right_eq_hi`,
  `left_eq_hi`, `right_eq_low`, `left_eq_low` - deferred, not blocking) and
  `right_sync_press` (gripper can't physically reach it - needs a different approach
  angle or fixture change to revisit). Crossfader, both channel faders, and 3 of 4
  cue/sync buttons ARE now taught - see START HERE.
- Phase 5 feedback-driven arm executor - not started. This is the actual next
  milestone; the crossfader being taught unblocks attempting it.
- `song_script.json` still only has the original V1 choreography - none of this
  session's newly-taught controls have been wired into an actual choreography yet,
  only taught and individually smoke-testable via `test_actions.py`.
- Real per-action arm latencies and the planner's arm travel-time table (measured in Phase 5).
- Knob `degrees_per_unit` is still a placeholder in `hardware/software/controls.json`.
- Only crossfader + volume are in the routine so far (v1 scope, by design - see
  `planner.py`'s docstring); EQ swaps and more sophisticated transition types are future
  work once Phase 4/5 prove the basic pipeline on the arm.
