"""Actually commands the MECA500 - connecting, activating, homing, and moving
to positions taught with teach.py.

Unlike teach.py (which only reads the robot's position in monitor mode),
this module takes real control and moves the arm.
"""
import json
import os
from mecademicpy.robot import Robot

from board_state import BoardState

ROBOT_IP = "192.168.0.100"
POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")
CONTROLS_FILE = os.path.join(os.path.dirname(__file__), "controls.json")


def load_positions():
    with open(POSITIONS_FILE) as f:
        return json.load(f)


def load_controls():
    with open(CONTROLS_FILE) as f:
        return json.load(f)


class MecaController:
    def __init__(self, ip=ROBOT_IP):
        self.robot = Robot()
        self.ip = ip
        self.positions = load_positions()
        self.controls = load_controls()
        self.state = BoardState()

    def connect(self):
        self.robot.Connect(address=self.ip)
        self.robot.ActivateRobot()
        self.robot.Home()
        self.robot.WaitHomed()

    def disconnect(self):
        self.robot.Disconnect()

    def go_home(self):
        self.move_to("home")

    def move_to(self, name, via=None):
        """Move to a named position from positions.json.

        via: optional name of a position to pass through first - use this to
        retract to a safe hover height before crossing the board or rotating
        joint 6 between the vertical/horizontal EOAT orientations, so the
        gripper never drags across a knob or fader at working depth.
        """
        if via is not None:
            self.move_to(via)
        if name not in self.positions:
            raise KeyError(f"No taught position named '{name}' in positions.json")
        self.robot.MoveJoints(*self.positions[name])
        self.robot.WaitIdle()

    def move_joints(self, joints):
        self.robot.MoveJoints(*joints)
        self.robot.WaitIdle()

    def move_slider(self, control, value):
        """Move a slider (fader/crossfader) to an absolute value in [0.0, 1.0].

        Assumes the gripper is already engaged with the slot at working
        depth (a `move_to` with `via` should have gotten it there first).
        Interpolates joint angles between the control's taught left/right
        endpoints - this is an absolute move, so it doesn't depend on
        BoardState at all, but we still record the resulting value so knob
        turns elsewhere in the script (which ARE relative) stay accurate.
        """
        cfg = self.controls[control]
        left = self.positions[cfg["left"]]
        right = self.positions[cfg["right"]]
        joints = [l + (r - l) * value for l, r in zip(left, right)]
        self.robot.MoveJoints(*joints)
        self.robot.WaitIdle()
        self.state.set(control, value)

    def turn_knob(self, control, value):
        """Turn a knob to an absolute value in [0.0, 1.0] via a RELATIVE
        joint-6 rotation - there's no absolute joint angle for "knob at 75%",
        only how far to turn it from wherever it currently is. That's why
        this needs BoardState: the delta is (target - last known value) *
        degrees_per_unit, not a taught position.

        Assumes the gripper is already engaged with the knob's cylindrical
        cutout at working depth. degrees_per_unit is not measured yet for
        any real knob - see README.
        """
        cfg = self.controls[control]
        current = self.state.get(control)
        delta_deg = (value - current) * cfg["degrees_per_unit"]
        self.robot.MoveJointsRel(0, 0, 0, 0, 0, delta_deg)
        self.robot.WaitIdle()
        self.state.set(control, value)
