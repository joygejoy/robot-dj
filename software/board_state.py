"""Tracks the current value of every continuous control (fader/knob) the
robot has moved, since the FLX4 board has no sensors to read this back -
it's just bookkeeping on our side.

Values are normalized 0.0-1.0 (0.0 = full counter-clockwise/left,
1.0 = full clockwise/right). Everything starts at 0.5 (center) per-run -
there's no persistence between runs, matching the assumption that a human
resets the physical board to center before each run.
"""

CENTER = 0.5


class BoardState:
    def __init__(self):
        self.values = {}

    def get(self, control):
        return self.values.get(control, CENTER)

    def set(self, control, value):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{control} value {value} out of range [0.0, 1.0]")
        self.values[control] = value
