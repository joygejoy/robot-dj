# Setting up the live Mixxx feed (Phase 1, Windows)

This guide walks a brand-new developer through getting a **live music feed** out of
Mixxx and into Python, one step at a time. That feed is the entire point of Phase 1:
before the robot can ever be timed to real music, we have to prove that plain Python
can read Mixxx's beat and position *as the track plays*, quickly and accurately.

You do **not** need the robot for any of this. This is all software on one Windows PC.

There are two ways to get the feed. Do **Option A (OSC) first** - it's simpler and
needs no extra software. Only fall back to **Option B (MIDI)** if your build of Mixxx
turns out not to have OSC.

---

## Step 0 - What you'll end up with

Two small "feed" programs. You only ever run ONE of them at a time:

- `live_feed.py` - listens for **OSC** messages from Mixxx (Option A).
- `midi_feed.py` - listens for **MIDI clock** from Mixxx (Option B).

Both feed their raw readings into `phase_lock.py`, which turns the lumpy, jittery
data into a smooth, always-answerable beat number and prints a live status line.

---

## Step 1 - Create the Python environment

Open **PowerShell** and go to the brain folder:

```powershell
cd C:\robot-dj\brain
```

Create a virtual environment (a private, project-local Python so these packages
don't collide with anything else on your machine) and activate it:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> If PowerShell blocks the activate script with an "execution policy" error, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer **Y**, then try
> activating again. This is normal on a fresh Windows install.

You'll know it worked when your prompt shows `(.venv)` at the front. Now install the
dependencies:

```powershell
pip install -r requirements.txt
```

That reads `requirements.txt` and installs `python-osc`, `python-rtmidi`, and `mido`.

---

## Option A (preferred) - OSC

OSC ("Open Sound Control") lets Mixxx send its live control values to any program
over the network. We run everything on one PC, so Mixxx sends to `127.0.0.1`
(that's "this same computer, talking to itself") on a port number we choose.

### A1. Turn on OSC in Mixxx

1. Open Mixxx.
2. Go to **Preferences** (gear icon, or `Options > Preferences`).
3. Look for an **OSC** section in the left-hand list.
4. Enable it. Set:
   - **Host / address:** `127.0.0.1`
   - **Port:** pick a number and remember it - this guide uses **`9000`**.

> **Heads-up: OSC support depends on your Mixxx version/build.** Not every Mixxx
> ships with OSC. If there is **no OSC section** in Preferences, don't fight it -
> skip straight to **Option B (MIDI)** below.

The **port number here must exactly match** the port you give the Python script
(`--port 9000`). A mismatch is the #1 reason "nothing shows up" - see Troubleshooting.

### A2. Discover the OSC address format

Here's the catch: **the exact OSC "addresses" Mixxx uses are version-dependent, and
we must NOT assume we already know them.** Different Mixxx builds label the same
values differently. So we look at what YOUR Mixxx actually sends, then teach the
script to match it. That's what discovery mode is for.

Run discovery (still in the activated `.venv`):

```powershell
python live_feed.py --discovery --port 9000
```

Now **play a track in Mixxx.** Move the crossfader, nudge the tempo, let it play.
The terminal will print every OSC address it receives, e.g. something shaped like:

```
/deck/1/play           1
/deck/1/bpm            128.0
/deck/1/beat_distance  0.42
...
```

Your addresses may look different - that's expected and exactly why we check.

### A3. Teach the script your address format

Open `live_feed.py` and find the `parse_address()` function. Edit it so it maps the
addresses **you just saw** onto the four things we care about, per deck:

- which deck (`[Channel1]` -> deck 1, `[Channel2]` -> deck 2)
- `play` (0/1)
- `bpm`
- `beat_distance` (0..1)

`parse_address()` has comments showing where to plug your values in. Change only the
string patterns to match your discovery output; leave the rest alone.

### A4. Run the live feed for real

```powershell
python live_feed.py --port 9000
```

Play a track. You should see a live status line updating many times a second, with
the **beat number climbing smoothly**. That's the feed working. Now go to the
**Success gate** below to confirm it's actually good enough.

---

## Option B (fallback) - MIDI

Use this only if your Mixxx has no OSC. Instead of OSC messages, we read **MIDI
clock**: a steady stream of pulses Mixxx sends, **24 pulses per beat** (per quarter
note). Counting those pulses tells us where the beat is.

Windows has no built-in "virtual MIDI cable," so we install one.

### B1. Install loopMIDI and create a port

1. Download and install **loopMIDI** (a free virtual-MIDI-port tool by Tobias Erichsen).
2. Open loopMIDI and click **+** to create a port. Leave the default name
   **`loopMIDI Port`** (or note whatever name you give it - you'll need it exactly).
3. **Leave loopMIDI running.** The port only exists while the app is open.

> **Order matters:** start loopMIDI and create the port **before** launching Mixxx.
> Mixxx only scans for MIDI ports at startup - a port created afterward won't appear
> until you restart Mixxx.

### B2. Point Mixxx's MIDI output at that port

1. In Mixxx **Preferences > Controllers**, find your **`loopMIDI Port`** in the list.
2. Enable it, and load an **output mapping** that emits MIDI clock/beat - the
   built-in **"MIDI for light"** output mapping works, or a custom output mapping
   that targets `loopMIDI Port`.
3. This makes Mixxx *send* MIDI (clock/beat) into the loop port, which our script
   then reads from the other end.

### B3. Find the port name Python sees

```powershell
python midi_feed.py --list-ports
```

This prints the MIDI input ports on your system. Copy the loopMIDI one **exactly** as
shown (Windows often appends a number, e.g. `loopMIDI Port 1`).

### B4. Run the MIDI feed

```powershell
python midi_feed.py --port "loopMIDI Port"
```

(Use the exact name from B3, in quotes.) Play a track. As with Option A, you should
see the **beat number advancing smoothly.** Continue to the Success gate.

---

## The success gate (this is the whole Phase 1)

**Phase 1 is proven ONLY when this holds, whichever option you used:**

> With a track playing, the terminal shows the **live beat number advancing smoothly**
> and it **stays accurate over ~3 minutes with no drift** - the beat count still lines
> up with the actual music at the end of the track, not running ahead or behind.

How to check accuracy by eye: pick a moment, note the beat number, and confirm the
whole-number part ticks up once per audible beat and the fractional part sweeps
`0.0 -> 1.0` once per beat. Over three minutes at, say, 128 bpm you should have counted
roughly `128 / 60 * 180 ≈ 384` beats. If the count and the music have visibly slipped
apart, that's **drift**, and it fails the gate.

**If the gate fails, STOP.** Do not start building later phases on a shaky feed.
Reassess first (usually a wrong OSC address mapping, a bpm that isn't coming through,
or a port problem - see below). A robot timed to a drifting clock is worse than useless.

---

## Troubleshooting

**Nothing prints at all (Option A / OSC).**
- **Port mismatch.** The port in Mixxx's OSC preferences must equal `--port`. If Mixxx
  sends to 9000 and you ran `--port 8000`, you'll see silence. Make them match.
- **Windows Firewall is blocking the UDP port.** OSC arrives as UDP packets, and the
  first time a Python program opens a UDP port Windows may pop a firewall prompt (or
  silently block it). Allow Python through the firewall for **Private networks**, or
  add an inbound rule for that UDP port. Since traffic is all `127.0.0.1` (this PC to
  itself), allowing local/private access is enough.
- Confirm a track is actually **playing** - many values only get sent when they change.

**No MIDI ports listed (Option B).**
- **loopMIDI isn't running**, or the port wasn't created. Open loopMIDI, add the port.
- **The port was created after Mixxx started.** Restart Mixxx so it re-scans, then run
  `--list-ports` again.
- Make sure you're passing the port name **exactly** as `--list-ports` shows it
  (including any trailing number), wrapped in quotes.

**The beat number jumps around or won't stay locked.**
- Double-check `bpm` is really coming through (Option A: is a bpm address mapped in
  `parse_address()`? Without tempo the smoother can't extrapolate cleanly).
- Confirm your `beat_distance` mapping is the 0..1 phase value, not something else.

**A note on `beat_active`.** Mixxx also exposes a `beat_active` flag, but it's only
accurate to about **~50 ms**, which is far too coarse to time a physical robot to.
That's why this project **never relies on `beat_active` alone** - `phase_lock.py`
derives the beat from **`beat_distance` + `bpm`** instead, which gives smooth,
sub-beat precision between samples.
