# Robot DJ

A MECA500 robot arm plays a DJ mixer (Pioneer DJM-FLX4) - moving faders,
turning knobs, pressing buttons - following a pre-scripted timeline synced
to a song. V1 is open-loop: no sensors checking whether it actually hit the
right spot, just a trusted, pre-taught sequence of moves.

## Repo layout

- Everything at the root (`*.SLDPRT`, `*.stp`, `board/`, `gripper*/`) is
  SolidWorks CAD for the mount, the FLX4 model, and the end-of-arm tool
  (EOAT). These files live on disk here but are **not tracked in git**
  (see `.gitignore`) - they're large binaries that don't diff meaningfully,
  and this repo is for the software side only.
- `software/` is all the Python that runs the show.

## Hardware

- MECA500 6-axis arm.
- End-of-arm tool (EOAT): a passive 3D-printed piece, no motor. It has a
  cylindrical cutout that turns a knob when lowered onto it, and a slot cut
  out that grips a slider. **There is no Arduino / separate motor
  controller** - the original plan assumed a motorized EOAT, but this one
  is purely mechanical, so the only thing under software control is the
  MECA arm itself.
- Robot has a fixed IP (`192.168.0.100`). Your PC's Ethernet adapter needs a
  static IP on the same subnet (e.g. `192.168.0.10 / 255.255.255.0`) to see
  it - Settings > Network > Ethernet > Edit IP assignment > Manual.

## How positions work

Positions are saved as 6 joint angles (degrees) in `software/positions.json`,
not XYZ coordinates. That was a deliberate call before any of this was
built: joint angles are unambiguous - the robot hits the exact same spot
every time, with no inverse-kinematics math that could resolve to the wrong
elbow/wrist configuration.

**Do you need to calibrate the board, or define its position in some
coordinate system?** No - not for V1. The board is mounted once and won't
move, and it only has a couple dozen fixed controls, so teaching each real
position by jogging the arm and recording it (via `teach.py`) is simpler
and more reliable than building a coordinate frame for the board (the kind
of thing `UR-Robots` does with `breadboard.py`, where positions are
generated relative to a reference hole because there are many boards and
they move between jobs). If this board ever gets bumped or remounted,
re-teach the affected positions. If you eventually need to support the
board moving/multiple boards, a breadboard-style reference-point system is
the natural next step - not needed now.

### Positions to teach, in order

1. **`home`** - safe position, clear of the board and the mixer. Move here
   before/after every run.
2. **`eoat_vertical_ref`** and **`eoat_horizontal_ref`** - two reference
   wrist orientations, 90 degrees apart on joint 6 only, matching the two
   ways the EOAT slot can engage a slider (vertical channel faders vs. the
   horizontal crossfader). Every taught position already bakes in whichever
   joint-6 angle you were at when you taught it - these two references exist
   so you can sanity-check a new position's joint-6 value against them and
   confirm it's oriented the way you meant it to be.
3. Real controls (faders, knobs, buttons) as you need them for the
   choreography.

### Safety pattern: hover, don't drag

Never reorient joint 6 or travel sideways while the gripper is down at
"working depth" (engaged with a knob/slider, or at button-press height).
Retract to a safe hover height first, reorient/translate there, then
descend onto the next target. `MecaController.move_to()` has a `via`
parameter for exactly this - pass the name of a safe hover position and it
moves there first. This is the same "hover + press" idea already decided
for buttons, just applied everywhere reorientation happens.

### Knob turns and slider moves (not proven out yet)

Not fully validated mechanically yet, so the software doesn't hard-code
assumptions here:
- **Knobs**: likely a relative joint-6 rotation while the cylindrical cutout
  is engaged.
- **Sliders**: likely a straight move between two taught endpoint positions
  (e.g. `crossfade_left` <-> `crossfade_right`) while the slot stays
  engaged - no rotation needed mid-move.

Once you've confirmed these mechanically, tune `degrees_per_unit` in
`controls.json` for real (see "Knob/slider state tracking" below).

## Knob/slider state tracking

The FLX4 has no sensors we can read, so the robot has no way to know where
a knob or slider physically is except by remembering what it last moved it
to. `board_state.py` is that memory: every continuous control is tracked as
a normalized value from `0.0` (full left/counter-clockwise) to `1.0` (full
right/clockwise), starting at `0.5` (center) - per the assumption that
someone resets the physical board to center before each run. State is
in-memory only, reset every run.

`controls.json` maps each control name to how it's actually moved:

- **`"type": "slider"`** - has taught `left`/`right` endpoint positions (from
  `positions.json`). `MecaController.move_slider(control, value)` linearly
  interpolates the 6 joint angles between those endpoints and moves there
  directly - an absolute move, so it doesn't need BoardState to work, but it
  still records the result.
- **`"type": "knob"`** - moved by a *relative* joint-6 rotation (no absolute
  angle means "knob at 75%"), so it needs a `degrees_per_unit` calibration
  constant (how many degrees of joint-6 rotation correspond to the knob's
  full 0.0-1.0 sweep). **Not measured yet** - the placeholder in
  `controls.json` is a guess. `MecaController.turn_knob(control, value)`
  reads the last known value from BoardState, computes the delta, and calls
  `MoveJointsRel`.

In `song_script.json`, use `{ "action": "move_slider", "control": "...",
"value": 0.0-1.0 }` or `{ "action": "turn_knob", "control": "...", "value":
0.0-1.0 }` alongside the existing `move_to`. Both assume the gripper is
already engaged at working depth - get it there with a preceding `move_to`
(using `via` to hover in first) before calling either.

## Files

- `software/positions.json` - taught positions (see above).
- `software/controls.json` - maps slider/knob names to how they're moved
  (see "Knob/slider state tracking" above).
- `software/board_state.py` - in-memory tracker for where each slider/knob
  currently is, since the board has no sensors to read this back.
- `software/teach.py` - jog with the MECA web interface, then run this to
  record the current joint angles under a name. Read-only/monitor mode -
  never moves the arm itself.
- `software/meca_controller.py` - actually commands the robot: connect,
  activate, home, move to a named position, move a slider, turn a knob.
- `software/song_script.json` - the choreography timeline (time in seconds
  from song start + an action).
- `software/runner.py` - plays the script: polls elapsed time in a tight
  loop (not `time.sleep()`, which would drift by however long each move
  actually takes) and dispatches each action when its time arrives.

## Build order

1. Connect to the MECA, teach `home`, `eoat_vertical_ref`,
   `eoat_horizontal_ref`.
2. Teach 3-4 real positions (a fader, a knob, a button) as a test.
3. Run `runner.py` against the example `song_script.json` to confirm
   sequencing/timing works.
4. Wire in real audio playback (e.g. `pygame`) so the timeline is synced to
   an actual song instead of wall-clock time from launch.
5. Teach the rest of the positions the real choreography needs, write the
   real `song_script.json` for the track.

## Setup

```
cd software
pip install -r requirements.txt
python teach.py
```
