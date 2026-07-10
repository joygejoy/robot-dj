"""Derive a position from an already-taught one via a Cartesian offset, using
the robot's own inverse kinematics instead of hand-computed joint angles.

Use this for positions defined as "same as X, but offset by a known Cartesian
amount" - e.g. a hover point is an engaged position pulled straight back
along robot X to the safe driving depth (same Y/Z/orientation, since the TCP
stays perpendicular to the board the whole time). Hand-computing that in
joint space isn't reliable on a 6-axis arm; asking the robot to do a linear
move and reading back the result is.

MOVES THE REAL ROBOT. Clear the board and be ready at the e-stop before
confirming the move prompt.

Usage:
  python derive_position.py right_mid_engage right_mid_hover --axis x --absolute 173.65
  python derive_position.py right_volume_top right_volume_half --axis z --relative -35
"""
import argparse
import json
import os
from mecademicpy.robot import Robot

ROBOT_IP = "192.168.0.100"
POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def load_positions():
    with open(POSITIONS_FILE) as f:
        return json.load(f)


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("from_pose", help="name of an already-taught position in positions.json")
    parser.add_argument("new_name", help="name to save the derived position under")
    parser.add_argument("--axis", choices=["x", "y", "z"], required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--absolute", type=float, help="target absolute Cartesian value (mm) on --axis")
    group.add_argument("--relative", type=float, help="relative Cartesian delta (mm) on --axis")
    args = parser.parse_args()

    positions = load_positions()
    if args.from_pose not in positions:
        raise SystemExit(f"'{args.from_pose}' not found in positions.json - teach or derive it first")
    if args.new_name in positions:
        confirm = input(f"'{args.new_name}' already exists - overwrite? (y/n): ").strip().lower()
        if confirm != "y":
            return

    robot = Robot()
    robot.Connect(address=ROBOT_IP)
    robot.ActivateRobot()
    robot.Home()
    robot.WaitHomed()
    try:
        input(
            f"About to move to '{args.from_pose}', then offset along {args.axis.upper()}. "
            "Board clear, hand near e-stop? Press Enter to continue..."
        )
        robot.MoveJoints(*positions[args.from_pose])
        robot.WaitIdle()

        axis_index = AXIS_INDEX[args.axis]
        if args.relative is not None:
            delta = args.relative
        else:
            current_pose = robot.GetPose()
            delta = args.absolute - current_pose[axis_index]

        offset = [0.0] * 6
        offset[axis_index] = delta
        robot.MoveLinRelWrf(*offset)
        robot.WaitIdle()

        joints = robot.GetJoints()
        positions[args.new_name] = joints
        save_positions(positions)
        print(f"Saved '{args.new_name}': {joints}")
    finally:
        robot.Disconnect()


if __name__ == "__main__":
    main()
