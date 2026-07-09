"""Actually commands the MECA500 - connecting, activating, homing, and moving
to positions taught with teach.py.

Unlike teach.py (which only reads the robot's position in monitor mode),
this module takes real control and moves the arm.
"""
import json
import os
from mecademicpy.robot import Robot

ROBOT_IP = "192.168.0.100"
POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")


def load_positions():
    with open(POSITIONS_FILE) as f:
        return json.load(f)


class MecaController:
    def __init__(self, ip=ROBOT_IP):
        self.robot = Robot()
        self.ip = ip
        self.positions = load_positions()

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
