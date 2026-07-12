"""Plays a song choreography from song_script.json.

Fires each action at the right time using a tight polling loop, not
time.sleep() - sleeping would drift by the sum of every move's real
duration, since a move can take longer than the gap to the next action.

Audio playback is not wired in yet (that's a later build step). For now
this runs against wall-clock time starting the moment the script launches.
"""
import json
import os
import time

from meca_controller import MecaController

SCRIPT_FILE = os.path.join(os.path.dirname(__file__), "song_script.json")


def load_script():
    with open(SCRIPT_FILE) as f:
        return json.load(f)


def dispatch(meca, action):
    if action["action"] == "move_to":
        meca.move_to(action["pose"])
    elif action["action"] == "drag_to":
        meca.drag_to(action["pose"])
    elif action["action"] == "move_slider":
        meca.move_slider(action["control"], action["value"])
    elif action["action"] == "turn_knob":
        meca.turn_knob(
            action["control"],
            action["value"],
            joint_vel=action.get("joint_vel"),
            min_duration=action.get("min_duration"),
        )
    else:
        raise ValueError(f"Unknown action type: {action['action']}")


def run():
    actions = sorted(load_script(), key=lambda a: a["time"])
    meca = MecaController()
    meca.connect()
    meca.go_home()

    print(f"Starting run: {len(actions)} action(s) queued.")
    start_time = time.time()
    next_index = 0
    try:
        while next_index < len(actions):
            elapsed = time.time() - start_time
            if actions[next_index]["time"] <= elapsed:
                action = actions[next_index]
                print(f"[{elapsed:.2f}s] {action['action']} -> {action.get('pose')}")
                dispatch(meca, action)
                next_index += 1
    finally:
        meca.retreat_to_safe()
        meca.disconnect()
        print("Run complete, retreated to safe depth.")


if __name__ == "__main__":
    run()
