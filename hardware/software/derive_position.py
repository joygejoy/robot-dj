"""Derive a position from an already-taught one via a Cartesian offset, using
the robot's own inverse kinematics instead of hand-computed joint angles.

Use this for positions defined as "same as X, but offset by a known Cartesian
amount" - e.g. a hover point is an engaged position pulled straight back
along robot X to the safe driving depth (same Y/Z/orientation, since the TCP
stays perpendicular to the board the whole time). Hand-computing that in
joint space isn't reliable on a 6-axis arm; asking the robot to do a linear
move and reading back the result is.

SAFETY: this never joint-moves (MoveJoints) straight to a working/engaged
position - MoveJoints interpolates all 6 joints together with no guaranteed
Cartesian path, which can clip the board on the way. Instead, for anything
other than home/safe_hover, the target pose is computed from the from_pose's
ALREADY-STORED pose (captured at teach time, no need to revisit it), and the
robot reaches it via safe_hover -> MoveLin (a genuine straight-line Cartesian
move) - safe as long as safe_hover and the target are both at a safe depth.

MOVES THE REAL ROBOT. Clear the board and be ready at the e-stop before
confirming the move prompt.

Usage:
  python derive_position.py home safe_hover --axis x --relative -30
  python derive_position.py right_mid_engage right_mid_hover --axis x --absolute 175
"""
import argparse
import json
import os
from mecademicpy.robot import Robot

ROBOT_IP = "192.168.0.100"
POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
SAFE_REFERENCE_POSITIONS = {"home", "safe_hover"}


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

    axis_index = AXIS_INDEX[args.axis]

    robot = Robot()
    robot.Connect(address=ROBOT_IP)
    robot.ActivateRobot()
    robot.Home()
    robot.WaitHomed()
    try:
        if args.from_pose in SAFE_REFERENCE_POSITIONS:
            # from_pose is itself a known-clear reference position (home or
            # safe_hover), so it's fine to joint-move straight to it.
            input(
                f"About to move to '{args.from_pose}' (safe reference), then offset "
                f"along {args.axis.upper()}. Board clear, hand near e-stop? "
                "Press Enter to continue..."
            )
            robot.MoveJoints(*positions[args.from_pose]["joints"])
            robot.WaitIdle()

            current_pose = robot.GetPose()
            if args.relative is not None:
                delta = args.relative
            else:
                delta = args.absolute - current_pose[axis_index]

            offset = [0.0] * 6
            offset[axis_index] = delta
            robot.MoveLinRelWrf(*offset)
            robot.WaitIdle()
        else:
            # from_pose is a working/engaged position near the board - never
            # joint-move straight to it. Compute the target from its stored
            # pose (captured at teach time) and approach it via a straight
            # Cartesian line from safe_hover instead.
            if "home" not in positions or "safe_hover" not in positions:
                raise SystemExit(
                    "'home' and 'safe_hover' must be taught/derived first - they're "
                    "the safe approach chain for this move."
                )
            base_pose = positions[args.from_pose]["pose"]
            target_pose = list(base_pose)
            if args.relative is not None:
                target_pose[axis_index] += args.relative
            else:
                target_pose[axis_index] = args.absolute

            input(
                f"About to move to 'home', then 'safe_hover', then straight-line "
                f"(MoveLin) to the pose computed from '{args.from_pose}' with "
                f"{args.axis.upper()} changed: {[round(v, 2) for v in target_pose]}. "
                "Board clear, hand near e-stop? Press Enter to continue..."
            )
            robot.MoveJoints(*positions["home"]["joints"])
            robot.WaitIdle()
            robot.MoveJoints(*positions["safe_hover"]["joints"])
            robot.WaitIdle()

            robot.MoveLin(*target_pose)
            robot.WaitIdle()

        joints = robot.GetJoints()
        pose = robot.GetPose()
        positions[args.new_name] = {"joints": joints, "pose": pose}
        save_positions(positions)
        print(f"Saved '{args.new_name}': joints={joints} pose={pose}")
    finally:
        robot.Disconnect()


if __name__ == "__main__":
    main()
