from dotenv import dotenv_values
import requests
import webbrowser
import websocket
import json
from lib.math import normalize_heading
import time
import math

FRONTEND_BASE = "noflight.monad.fi"
BACKEND_BASE = "noflight.monad.fi/backend"

game_id = None


def on_message(ws: websocket.WebSocketApp, message):
    [action, payload] = json.loads(message)

    if action != "game-instance":
        print([action, payload])
        return

    # New game tick arrived!
    game_state = json.loads(payload["gameState"])
    commands = generate_commands(game_state)

    time.sleep(0.1)
    ws.send(json.dumps(
        ["run-command", {"gameId": game_id, "payload": commands}]))


def on_error(ws: websocket.WebSocketApp, error):
    print(error)


def on_open(ws: websocket.WebSocketApp):
    print("OPENED")
    ws.send(json.dumps(["sub-game", {"id": game_id}]))


def on_close(ws, close_status_code, close_msg):
    print("CLOSED")


def find_destination_airport(_airports, _destination_letter):
    for airport in _airports:
        if (airport['name'] == _destination_letter):
            return airport


def find_airport_direction_and_position(_airports, _destination_letter):
    destination = find_destination_airport(_airports, _destination_letter)
    airport_dir = int(destination['direction'])
    airport_pos_x = int(destination['position']['x'])
    airport_pos_y = int(destination['position']['y'])
    return airport_dir, airport_pos_x, airport_pos_y


def calculate_airport_turning_and_front_points(_airport_pos_x,
                                               _airport_pos_y, _airport_dir):

    airport_opposite_dir = normalize_heading(_airport_dir+180)

    airport_turning_x = _airport_pos_x + round(40*math.cos(
        (airport_opposite_dir/360)*2*math.pi))
    airport_turning_y = _airport_pos_y + round(40*math.sin(
        (airport_opposite_dir/360)*2*math.pi))
    airport_front_x = _airport_pos_x + round(10*math.cos(
        (airport_opposite_dir/360)*2*math.pi))
    airport_front_y = _airport_pos_y + round(10*math.sin(
        (airport_opposite_dir/360)*2*math.pi))

    return (airport_turning_x, airport_turning_y,
            airport_front_x, airport_front_y)


def calculate_direction_to_point(_destination_pos_y, _aircraft_pos_y,
                                 _destination_pos_x, _aircraft_pos_x):
    direction = normalize_heading(
            math.degrees(
                2*math.pi + math.atan2(
                                        _destination_pos_y-_aircraft_pos_y,
                                        _destination_pos_x-_aircraft_pos_x)))
    return direction


def calculate_airport_boundary_lines(_airport_pos_x,
                                     _airport_pos_y, _airport_dir):

    airport_side_1_x = _airport_pos_x + round(10*math.cos(
        ((_airport_dir-90)/360)*2*math.pi))
    airport_side_1_y = _airport_pos_y + round(10*math.sin(
        ((_airport_dir-90)/360)*2*math.pi))
    airport_side_2_x = _airport_pos_x + round(10*math.cos(
        ((_airport_dir+90)/360)*2*math.pi))
    airport_side_2_y = _airport_pos_y + round(10*math.sin(
        ((_airport_dir+90)/360)*2*math.pi))

    boundary_lines_slope = math.tan(math.radians(_airport_dir % 180))

    line_1_values = [boundary_lines_slope, airport_side_1_x, airport_side_1_y]
    line_2_values = [boundary_lines_slope, airport_side_2_x, airport_side_2_y]

    return line_1_values, line_2_values


def check_if_plane_is_on_right_side(_airport_dir, _airport_pos_x,
                                    _airport_pos_y, _aircraft_pos_x,
                                    _aircraft_pos_y):

    airport_back_point_x = _airport_pos_x + round(10*math.cos(
        ((_airport_dir)/360)*2*math.pi))
    airport_back_point_y = _airport_pos_y + round(10*math.sin(
        ((_airport_dir)/360)*2*math.pi))

    airport_diameter_slope = math.tan(math.radians((_airport_dir-90) % 180))
    y_aircraft = (airport_diameter_slope *
                  (_aircraft_pos_x-airport_back_point_x)+airport_back_point_y)
    y_airport_center = (airport_diameter_slope *
                        (_airport_pos_x-airport_back_point_x) +
                        airport_back_point_y)

    # Plane is on right side if it's on the same
    # side of the line than the airport center
    return ((y_aircraft < _aircraft_pos_y) ==
            (y_airport_center < _airport_pos_y))


def check_if_plane_is_between_lines(_aircraft_pos_x,
                                    _aircraft_pos_y, _airport_pos_x,
                                    _airport_pos_y, _airport_dir):

    boundary_lines = calculate_airport_boundary_lines(_airport_pos_x,
                                                      _airport_pos_y,
                                                      _airport_dir)

    y1 = (boundary_lines[0][0] *
          (_aircraft_pos_x-boundary_lines[0][1])+boundary_lines[0][2])
    y2 = (boundary_lines[1][0] *
          (_aircraft_pos_x-boundary_lines[1][1])+boundary_lines[1][2])

    plane_between_lines = ((y1 <= _aircraft_pos_y <= y2)
                           or (y2 <= _aircraft_pos_y <= y1))

    return plane_between_lines


def check_if_plane_is_going_towards_airport(_airport_dir, _aircraft_dir):
    difference = _airport_dir-_aircraft_dir
    shortest_turn = abs((difference + 180) % 360-180)
    return (shortest_turn < 90)


def calculate_dirs_to_front_and_turning_points(_aircraft, _airport_pos_x,
                                               _airport_pos_y, _airport_dir):

    (airport_turning_x,
     airport_turning_y,
     airport_front_x,
     airport_front_y) = calculate_airport_turning_and_front_points(
                                            _airport_pos_x,
                                            _airport_pos_y, _airport_dir)

    airport_front_direction = calculate_direction_to_point(
                airport_front_y, _aircraft['position']['y'],
                airport_front_x, _aircraft['position']['x'])

    turning_point_direction = calculate_direction_to_point(
                airport_turning_y, _aircraft['position']['y'],
                airport_turning_x, _aircraft['position']['x'])

    return airport_front_direction, turning_point_direction


def calculate_right_direction(_plane_on_right_side_of_the_airport,
                              _plane_on_landing_sector,
                              _plane_flying_towards_airport,
                              _airport_direction,
                              _airport_front_direction,
                              _turning_point_direction,
                              _distance_to_airport):

    if (_plane_on_right_side_of_the_airport and _plane_on_landing_sector and
            _plane_flying_towards_airport):
        right_direction = _airport_direction

    elif (_plane_on_right_side_of_the_airport
            and _plane_flying_towards_airport):
        right_direction = _airport_front_direction

    elif (_plane_on_right_side_of_the_airport
            and _distance_to_airport >= 40):
        right_direction = _airport_front_direction

    else:
        right_direction = _turning_point_direction

    return right_direction


def calculate_direction_change(_right_direction,
                               _aircraft_direction):

    if (_right_direction != _aircraft_direction):
        direction_diff = abs(_aircraft_direction - _right_direction)

        if (direction_diff > 20):
            direction_change = 20
        else:
            direction_change = direction_diff

        if (normalize_heading(_right_direction - _aircraft_direction) >= 180):
            direction_change = -1*direction_change
    else:
        direction_change = 0

    return direction_change


def generate_commands(_game_state):
    commands = []
    for aircraft in _game_state['aircrafts']:

        (airport_direction,
         airport_pos_x,
         airport_pos_y) = find_airport_direction_and_position(
                                    _game_state['airports'],
                                    aircraft['destination'])

        (airport_front_direction,
         turning_point_direction) = calculate_dirs_to_front_and_turning_points(
                                            aircraft, airport_pos_x,
                                            airport_pos_y, airport_direction)

        plane_on_landing_sector = check_if_plane_is_between_lines(
                                    aircraft['position']['x'],
                                    aircraft['position']['y'],
                                    airport_pos_x, airport_pos_y,
                                    airport_direction)

        plane_on_right_side_of_the_airport = check_if_plane_is_on_right_side(
                                                airport_direction,
                                                airport_pos_x,
                                                airport_pos_y,
                                                aircraft['position']['x'],
                                                aircraft['position']['y'])

        plane_flying_towards_airport = check_if_plane_is_going_towards_airport(
                                    airport_direction, aircraft['direction'])

        distance_to_airport = math.dist([airport_pos_x, airport_pos_y],
                                        [aircraft['position']['x'],
                                         aircraft['position']['y']])

        right_direction = calculate_right_direction(
                            plane_on_right_side_of_the_airport,
                            plane_on_landing_sector,
                            plane_flying_towards_airport,
                            airport_direction,
                            airport_front_direction,
                            turning_point_direction,
                            distance_to_airport)

        direction_change = calculate_direction_change(
                                right_direction, aircraft['direction'])

        if (direction_change != 0):
            new_direction = normalize_heading(
                            aircraft['direction'] + direction_change)
            commands.append(f"HEAD {aircraft['id']} {new_direction}")

    return commands


def main():
    config = dotenv_values()
    res = requests.post(
        f"https://{BACKEND_BASE}/api/levels/{config['LEVEL_ID']}",
        headers={
            "Authorization": config["TOKEN"]
        })

    if not res.ok:
        print(f"Couldn't create game: {res.status_code} - {res.text}")
        return

    game_instance = res.json()

    global game_id
    game_id = game_instance["entityId"]

    url = f"https://{FRONTEND_BASE}/?id={game_id}"
    print(f"Game at {url}")
    webbrowser.open(url, new=2)
    time.sleep(2)

    ws = websocket.WebSocketApp(
        f"wss://{BACKEND_BASE}/{config['TOKEN']}/", on_message=on_message, on_open=on_open, on_close=on_close, on_error=on_error)
    ws.run_forever()


if __name__ == "__main__":
    main()
