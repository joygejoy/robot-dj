// Robot DJ V2 - Mixxx OUTPUT mapping: "beat feed"
// =================================================
//
// WHAT THIS IS
// ------------
// A tiny Mixxx controller *output* script whose only job is to push the two
// numbers our Python phase-lock needs - the beat phase (beat_distance, 0..1) and
// the tempo (bpm) - plus a play flag, out of Mixxx as plain MIDI Control-Change
// (CC) messages. It is the MIDI stand-in for the OSC feed Mixxx can't give us on
// this build: same data (beat_distance + bpm + playing, PER DECK), different pipe.
//
// WHY NOT THE STOCK "MIDI for light" MAPPING?
// -------------------------------------------
// That preset sends VU meters, an MTC timecode, and a once-per-beat "beat_active"
// note - but NO continuous beat phase and NO true MIDI clock. Our phase-lock is
// built around a smooth 0..1 beat_distance, which "MIDI for light" never emits.
// So we send our own.
//
// HOW THE DATA IS PACKED (must match midi_cc_feed.py on the Python side)
// ----------------------------------------------------------------------
// All messages are Control-Change on MIDI channel 1 (status byte 0xB0).
// Each deck gets a block of 4 CC numbers:
//
//     field            deck 1 CC     deck 2 CC     meaning
//     ---------------  -----------   -----------   ------------------------------
//     beat_distance    20 (MSB)      24 (MSB)      14-bit phase, high 7 bits
//                      21 (LSB)      25 (LSB)      14-bit phase, low 7 bits
//     bpm              22            26            round(bpm - 50), 0..127
//     playing          23            27            127 = playing, 0 = stopped
//
// beat_distance is sent as 14 bits (two 7-bit CCs) because 7 bits alone (1/128 of
// a beat) is coarser than we'd like for timing a physical arm; 14 bits gives
// ~1/16000 of a beat, far finer than we need, with headroom to spare.
//
// ORDER MATTERS: we send playing, bpm, MSB, then the LSB LAST. The Python side
// treats the LSB as the "this frame is complete" trigger and only then updates
// its estimate - so every other field is guaranteed fresh by the time it fires.

var RobotDJBeatFeed = {};

// Which Mixxx decks to report. [Channel1] and [Channel2] are the two main decks.
RobotDJBeatFeed.decks = [1, 2];

// How often to push a fresh frame, in milliseconds. ~33 frames/sec. The stock
// "MIDI for light" mapping uses a 40 ms timer for its VU meters, so this cadence
// is a proven, comfortable load for Mixxx + loopMIDI. The Python phase-lock
// extrapolates smoothly between frames using bpm, so this rate is plenty.
RobotDJBeatFeed.sendIntervalMs = 30;

RobotDJBeatFeed.timer = 0;

// MIDI status byte for Control-Change on channel 1.
RobotDJBeatFeed.STATUS_CC = 0xB0;

// First CC number for each deck's 4-field block (see table above).
RobotDJBeatFeed.baseCC = { 1: 20, 2: 24 };

// We transmit bpm as (bpm - 50) so it fits a 0..127 byte. This mirrors the
// convention the stock "MIDI for light" mapping already uses for its BPM note,
// and covers 50..177 bpm - the whole realistic DJ range.
RobotDJBeatFeed.BPM_OFFSET = 50;

// Called once when Mixxx opens this "controller". We just start the repeating
// timer; all the work happens in sendFrame().
RobotDJBeatFeed.init = function(id) {
    RobotDJBeatFeed.timer = engine.beginTimer(
        RobotDJBeatFeed.sendIntervalMs, RobotDJBeatFeed.sendFrame);
};

// Called when Mixxx closes the controller - stop the timer so it doesn't leak.
RobotDJBeatFeed.shutdown = function() {
    if (RobotDJBeatFeed.timer) {
        engine.stopTimer(RobotDJBeatFeed.timer);
        RobotDJBeatFeed.timer = 0;
    }
};

// Clamp a number into a valid single MIDI data byte (integer 0..127).
RobotDJBeatFeed.clamp7 = function(v) {
    v = Math.round(v);
    if (v < 0) { return 0; }
    if (v > 127) { return 127; }
    return v;
};

// The heartbeat: read each deck and emit its 4 CC messages.
RobotDJBeatFeed.sendFrame = function() {
    for (var i = 0; i < RobotDJBeatFeed.decks.length; i++) {
        var deck = RobotDJBeatFeed.decks[i];
        var group = "[Channel" + deck + "]";
        var base = RobotDJBeatFeed.baseCC[deck];

        var playing = engine.getValue(group, "play") ? 127 : 0;
        var bpm = engine.getValue(group, "bpm");                    // 0 if no track loaded
        var beatDistance = engine.getValue(group, "beat_distance"); // 0..1 phase within the beat

        // Pack beat_distance into 14 bits split across two 7-bit bytes.
        var bd14 = Math.round(beatDistance * 16383);
        if (bd14 < 0) { bd14 = 0; }
        if (bd14 > 16383) { bd14 = 16383; }
        var bdMsb = (bd14 >> 7) & 0x7F;
        var bdLsb = bd14 & 0x7F;

        var bpmByte = RobotDJBeatFeed.clamp7(bpm - RobotDJBeatFeed.BPM_OFFSET);

        // playing, bpm, MSB, then LSB LAST (LSB is the "frame complete" trigger).
        midi.sendShortMsg(RobotDJBeatFeed.STATUS_CC, base + 3, playing);
        midi.sendShortMsg(RobotDJBeatFeed.STATUS_CC, base + 2, bpmByte);
        midi.sendShortMsg(RobotDJBeatFeed.STATUS_CC, base + 0, bdMsb);
        midi.sendShortMsg(RobotDJBeatFeed.STATUS_CC, base + 1, bdLsb);
    }
};
