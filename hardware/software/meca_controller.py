"""Actually commands the MECA500 - connecting, activating, homing, and moving
to positions taught with teach.py.

Unlike teach.py (which only reads the robot's position in monitor mode),
this module takes real control and moves the arm.
"""
import json
import os
import time
from mecademicpy.robot import Robot

from board_state import BoardState

ROBOT_IP = "192.168.0.100"
POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")
CONTROLS_FILE = os.path.join(os.path.dirname(__file__), "controls.json")

# The measured safe clearance depth (mm, robot X / world-frame X) - the same
# value used with derive_position.py's --absolute flag to build every hover
# position. All board-crossing transit happens at this X; only the final
# dive into a working/engaged position goes past it.
SAFE_X = 175.0

# Cartesian linear speed (mm/s) for legs that approach/leave working depth
# (dive-in, retract, and drag_to) - where a bad move would actually make
# contact with something.
DIVE_VEL = 20.0

# Pacing interval (seconds) between steps of a min_duration-paced knob turn -
# see turn_knob(). SetJointVel is a percentage of the robot's max joint
# speed, which we don't know in deg/s, so it can't reliably guarantee a
# specific wall-clock duration on its own; explicit step pacing can.
KNOB_STEP_INTERVAL = 0.1

# Engaged/working position -> its safe hover counterpart. Cross-board
# transit always routes through the hover's REAL, already-validated joint
# values (via MoveJoints) rather than a synthesized Cartesian point - see
# move_to()'s docstring for why.
HOVER_FOR = {
    "right_mid_engage": "right_mid_hover",
    "right_volume_top": "right_volume_top_hover",
    "right_volume_75": "right_volume_75_hover",
    "right_volume_half": "right_volume_half_hover",
    "right_play_press": "right_play_hover",
    "left_play_press": "left_play_hover",
    "left_filter_engage": "left_filter_hover",
}


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
        """Bootstrap only - reach a known, board-relative position from the
        robot's own arbitrary built-in homing pose. Raw joint moves through
        the already-validated-safe chain (this is the ONE place we still
        trust MoveJoints for a multi-position hop, since GetPose() isn't
        board-relative-meaningful yet at this point in a session).
        """
        self.robot.MoveJoints(*self.positions["home"]["joints"])
        self.robot.WaitIdle()
        self.robot.MoveJoints(*self.positions["safe_hover"]["joints"])
        self.robot.WaitIdle()

    def _get_target_pose(self, name):
        if name not in self.positions:
            raise KeyError(f"No taught position named '{name}' in positions.json")
        target_pose = self.positions[name]["pose"]
        if target_pose is None:
            raise ValueError(
                f"'{name}' has no stored Cartesian pose - re-teach it with the "
                "current teach.py (or re-derive it) before using it with move_to."
            )
        return target_pose

    def move_to(self, name):
        """Move to a named position from positions.json.

          1. If currently deeper than SAFE_X (engaged on something), retract
             straight back to SAFE_X at the CURRENT Y/Z (MoveLin - pure X
             change, nothing else moves). Guaranteed safe: a straight line
             on a single axis always succeeds.
          2. Cross the board to the target's hover counterpart (MoveJoints,
             using that hover's REAL, already-validated joint values from
             positions.json - not a synthesized Cartesian point). A single
             straight-line MoveLin across a big lateral distance can fail
             with MX_ST_OUT_OF_REACH even when both endpoints are
             individually fine and both at SAFE_X - confirmed on the real
             robot going from right_volume to left_play. The arm's
             reachable workspace isn't a flat plane at constant X, so
             holding X fixed during a big sweep isn't always possible.
             MoveJoints has no such reachability limit, and both endpoints
             here are safely retracted, off-board configurations - a lower
             risk category than the original bug (jumping to/from working
             depth with no known-safe path).
          3. Dive straight in along X to the target's actual pose (MoveLin,
             pure X change, since Y/Z/orientation already match the hover -
             skipped if the target already IS a hover position).
        """
        if name not in self.positions:
            raise KeyError(f"No taught position named '{name}' in positions.json")
        hover_name = HOVER_FOR.get(name, name)
        hover_joints = self.positions[hover_name]["joints"]

        current_pose = self.robot.GetPose()
        self.robot.SetCartLinVel(DIVE_VEL)
        if current_pose[0] > SAFE_X:
            retract_pose = list(current_pose)
            retract_pose[0] = SAFE_X
            self.robot.MoveLin(*retract_pose)
            self.robot.WaitIdle()

        self.robot.MoveJoints(*hover_joints)
        self.robot.WaitIdle()

        if hover_name != name:
            target_pose = self._get_target_pose(name)
            self.robot.SetCartLinVel(DIVE_VEL)
            self.robot.MoveLin(*target_pose)
            self.robot.WaitIdle()

    def drag_to(self, name):
        """Move directly to another position of the SAME already-engaged
        control (e.g. right_volume_top <-> right_volume_half) - a straight
        MoveLin with no retract, since these controls (sliders) only move
        if dragged while still gripped. Retracting first would release the
        slider, leaving it wherever it physically was, then dive back in at
        the wrong height - it wouldn't actually get moved.
        """
        target_pose = self._get_target_pose(name)
        self.robot.SetCartLinVel(DIVE_VEL)
        self.robot.MoveLin(*target_pose)
        self.robot.WaitIdle()

    def retreat_to_safe(self):
        """End-of-run parking: retract straight out to SAFE_X at whatever
        Y/Z the arm currently happens to be at. Always safe (pure X change,
        no Y/Z change) - doesn't require navigating all the way back to the
        taught 'home' position, which isn't needed just to park safely.
        """
        current_pose = self.robot.GetPose()
        if current_pose[0] > SAFE_X:
            retract_pose = list(current_pose)
            retract_pose[0] = SAFE_X
            self.robot.SetCartLinVel(DIVE_VEL)
            self.robot.MoveLin(*retract_pose)
            self.robot.WaitIdle()

    def move_joints(self, joints):
        self.robot.MoveJoints(*joints)
        self.robot.WaitIdle()

    def move_slider(self, control, value):
        """Move a slider (fader/crossfader) to an absolute value in [0.0, 1.0].

        Assumes the gripper is already engaged with the slot at working
        depth (a `move_to` call should have gotten it there first).
        Interpolates joint angles between the control's taught left/right
        endpoints - this is an absolute move, so it doesn't depend on
        BoardState at all, but we still record the resulting value so knob
        turns elsewhere in the script (which ARE relative) stay accurate.
        """
        cfg = self.controls[control]
        left = self.positions[cfg["left"]]["joints"]
        right = self.positions[cfg["right"]]["joints"]
        joints = [l + (r - l) * value for l, r in zip(left, right)]
        self.robot.MoveJoints(*joints)
        self.robot.WaitIdle()
        self.state.set(control, value)

    def turn_knob(self, control, value, joint_vel=None, min_duration=None):
        """Turn a knob to an absolute value in [0.0, 1.0] via a RELATIVE
        joint-6 rotation - there's no absolute joint angle for "knob at 75%",
        only how far to turn it from wherever it currently is. That's why
        this needs BoardState: the delta is (target - last known value) *
        degrees_per_unit, not a taught position.

        Assumes the gripper is already engaged with the knob's cylindrical
        cutout at working depth. degrees_per_unit is not measured yet for
        any real knob - see README.

        joint_vel: optional override (percentage of max joint velocity) for
        a single continuous turn.
        min_duration: optional minimum wall-clock time (seconds) to stretch
        the turn across, for a deliberately slow/gradual motion regardless
        of the robot's actual joint speed. SetJointVel is a percentage of an
        unknown-to-us max deg/s, so it can't reliably hit a target duration
        on its own - this instead splits the turn into small steps paced
        with time.sleep() to guarantee the floor.
        """
        cfg = self.controls[control]
        current = self.state.get(control)
        delta_deg = (value - current) * cfg["degrees_per_unit"]

        if joint_vel is not None:
            self.robot.SetJointVel(joint_vel)

        if min_duration:
            steps = max(1, round(min_duration / KNOB_STEP_INTERVAL))
            step_delta = delta_deg / steps
            for _ in range(steps):
                step_start = time.time()
                self.robot.MoveJointsRel(0, 0, 0, 0, 0, step_delta)
                self.robot.WaitIdle()
                remaining = KNOB_STEP_INTERVAL - (time.time() - step_start)
                if remaining > 0:
                    time.sleep(remaining)
        else:
            self.robot.MoveJointsRel(0, 0, 0, 0, 0, delta_deg)
            self.robot.WaitIdle()

        self.state.set(control, value)
