# Robot DJ V2 - the "brain" (`C:\robot-dj\brain\`)

This folder is the **music-listening brain** for Robot DJ V2. It is separate from the
robot "body" code in `C:\robot-dj\hardware\software\` (which drives the MECA500 arm and
is not touched here).

## What Phase 1 is

A MECA500 robot arm physically plays a Pioneer DDJ-FLX4 controller, and we're moving the
audio into **Mixxx** (open-source DJ software). Later phases will time the robot's real
moves to the real music. Before any of that, **Phase 1 proves one thing only:** that
plain Python can read Mixxx's **live beat and position** with low latency and no drift.

That's the whole goal. No robot, no choreography yet - just a trustworthy live feed.

## The files

| File | Role |
|------|------|
| `phase_lock.py` | The correctness-critical core. Takes lumpy, jittery beat samples and produces a **smooth, always-answerable beat number** (whole beats + phase). Standard library only, so it's unit-testable anywhere. |
| `live_feed.py` | **Option A feed (preferred):** receives Mixxx's data over **OSC** and pushes it into `phase_lock.py`. Has a `--discovery` mode to learn your Mixxx's OSC addresses. |
| `midi_feed.py` | **Option B feed (fallback):** reads **MIDI clock** (24 pulses/beat) from Mixxx via a virtual port and pushes it into `phase_lock.py`. Use only if your Mixxx lacks OSC. |
| `test_phase_lock.py` | Unit tests for `phase_lock.py`, using a fake clock and hand-fed samples. Run with no Mixxx and no hardware. |
| `SETUP_MIXXX_FEED.md` | Step-by-step Windows setup: environment, install, both feed options, the success gate, and troubleshooting. **Start here to get a feed running.** |
| `requirements.txt` | Python deps for the feed scripts (`python-osc`, `python-rtmidi`, `mido`). |

## How the pieces relate

```
        Mixxx (playing a track)
               |
     OSC  -----+-----  MIDI
      |                  |
 live_feed.py       midi_feed.py     <- pick ONE, depending on your Mixxx
      \                  /
       \                /
        phase_lock.py            <- smooths + counts beats (stdlib only, tested)
              |
        live status line in the terminal
```

You run **one** feed script at a time. Both hand their raw readings to the same
`phase_lock.py`, which does the smoothing and prints the live beat. `test_phase_lock.py`
checks that smoothing logic in isolation, needing neither Mixxx nor hardware.

## Getting started

Read **`SETUP_MIXXX_FEED.md`** and follow it top to bottom. Phase 1 succeeds when a
playing track shows a beat number advancing smoothly with **no drift over ~3 minutes**.
