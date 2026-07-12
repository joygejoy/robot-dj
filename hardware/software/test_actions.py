"""Test individual robot actions in isolation, without running the full
song_script.json timeline.

Every action retraces the same hover-then-engage / hover-then-press pattern
song_script.json uses. `move-to` deliberately stops at the safe hover height
and never dives to working depth - it's for checking a position lines up
correctly before trusting it in the real choreography.

MOVES THE REAL ROBOT.

Usage:
  python test_actions.py move-to <position_name>
  python test_actions.py turn-knob <right_mid|left_filter> <degrees> <left|right>
  python test_actions.py press-button <right_play|left_play>
"""
import argparse

from meca_controller import MecaController, HOVER_FOR

KNOBS = {
    "right_mid": {"engage": "right_mid_engage", "hover": "right_mid_hover"},
    "left_filter": {"engage": "left_filter_engage", "hover": "left_filter_hover"},
}

BUTTONS = {
    "right_play": {"press": "right_play_press", "hover": "right_play_hover"},
    "left_play": {"press": "left_play_press", "hover": "left_play_hover"},
}


def cmd_move_to(mc, name):
    if name not in mc.positions:
        raise SystemExit(f"'{name}' not in positions.json")
    target = HOVER_FOR.get(name, name)
    if target not in mc.positions:
        raise SystemExit(
            f"'{name}' needs its hover counterpart '{target}' taught first "
            "(see derive_position.py) before it can be tested safely."
        )
    print(f"Moving to '{target}' (transit at safe X, no dive)...")
    mc.move_to(target)
    print("Done.")


def cmd_turn_knob(mc, knob, degrees, direction):
    cfg = KNOBS[knob]
    delta = -degrees if direction == "left" else degrees
    print(f"Moving to '{cfg['hover']}', then engaging '{cfg['engage']}'...")
    mc.move_to(cfg["hover"])
    mc.move_to(cfg["engage"])
    print(f"Rotating joint 6 by {delta:+.1f} deg ({direction})...")
    mc.robot.MoveJointsRel(0, 0, 0, 0, 0, delta)
    mc.robot.WaitIdle()
    print(f"Retracting to '{cfg['hover']}'...")
    mc.move_to(cfg["hover"])
    print("Done.")


def cmd_press_button(mc, button):
    cfg = BUTTONS[button]
    print(f"Moving to '{cfg['hover']}'...")
    mc.move_to(cfg["hover"])
    print(f"Pressing: moving to '{cfg['press']}'...")
    mc.move_to(cfg["press"])
    print(f"Retracting to '{cfg['hover']}'...")
    mc.move_to(cfg["hover"])
    print("Done.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_move = sub.add_parser("move-to", help="drive to a position's safe hover height, no dive")
    p_move.add_argument("name")

    p_knob = sub.add_parser("turn-knob", help="engage a knob and rotate it a specified amount")
    p_knob.add_argument("knob", choices=list(KNOBS))
    p_knob.add_argument("degrees", type=float)
    p_knob.add_argument("direction", choices=["left", "right"])

    p_button = sub.add_parser("press-button", help="engage a button and press it")
    p_button.add_argument("button", choices=list(BUTTONS))

    args = parser.parse_args()

    mc = MecaController()
    mc.connect()
    mc.go_home()
    try:
        if args.cmd == "move-to":
            cmd_move_to(mc, args.name)
        elif args.cmd == "turn-knob":
            cmd_turn_knob(mc, args.knob, args.degrees, args.direction)
        elif args.cmd == "press-button":
            cmd_press_button(mc, args.button)
    finally:
        mc.disconnect()


if __name__ == "__main__":
    main()
