"""Capture robot positions for the DJ robot project.

How to use:
1. Open the Mecademic web interface (http://192.168.0.100) and jog the arm
   to wherever you want the gripper to land. Leave that browser tab open the
   whole time.
2. Come back to this terminal, type a name for that spot, and press Enter.
3. This script reads the arm's CURRENT joint angles and saves them into
   positions.json under that name. It never moves the arm itself.
4. Type "done" when you're finished teaching positions for this session.

This connects in monitor mode (read-only), so it will not fight with the
web interface for control of the robot - you keep jogging from the browser,
this script just records where you end up.

TEACHING ORDER (teach these first, in this order):
  1. home              - safe position, clear of the board and the mixer
  2. eoat_vertical_ref  - gripper's slot oriented for a vertical slider
  3. eoat_horizontal_ref - gripper's slot rotated 90 deg (joint 6 only) for
                           a horizontal slider (e.g. the crossfader)
  Then teach real controls (faders, knobs, buttons) as you need them.
"""
import json
import os
from mecademicpy.robot import Robot

ROBOT_IP = "192.168.0.100"
POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {}


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def main():
    positions = load_positions()

    robot = Robot()
    robot.Connect(address=ROBOT_IP, monitor_mode=True)
    print(f"Connected to {ROBOT_IP} in monitor mode (read-only - this will not move the arm).")
    print("Jog the arm into position using the web interface, then come back here.\n")

    try:
        while True:
            name = input("Name for this position (or 'done' to quit): ").strip()
            if name.lower() == "done":
                break
            if not name:
                continue
            if name in positions:
                confirm = input(f"'{name}' already exists - overwrite? (y/n): ").strip().lower()
                if confirm != "y":
                    continue

            joints = robot.GetJoints()
            positions[name] = joints
            save_positions(positions)
            print(f"Saved '{name}': {joints}\n")
    finally:
        robot.Disconnect()
        print(f"\nSaved {len(positions)} position(s) to {POSITIONS_FILE}")


if __name__ == "__main__":
    main()
