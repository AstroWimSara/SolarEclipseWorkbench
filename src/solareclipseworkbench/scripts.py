import io
import csv
import logging
from datetime import datetime, timedelta

from solareclipseworkbench.hardware_registry import HARDWARE_COMMANDS


def convert_command(line, ref_moment, sign, time_delta, extra_comment, output_file) -> io.StringIO:
    try:
        return _convert_command(line, ref_moment, sign, time_delta, extra_comment, output_file)
    except (ValueError, IndexError) as e:
        # Too few fields for the command, or a field that cannot be read.  The
        # line cannot run, and that has to be visible at load time.
        logging.warning("Script line cannot be read (%s) — this line will NOT run: %s", e, str(line).strip())
        return output_file


def _convert_command(line, ref_moment, sign, time_delta, extra_comment, output_file) -> io.StringIO:
    # Use CSV parser to properly handle quoted fields with commas
    try:
        command_parts = next(csv.reader([line], skipinitialspace=True))
    except (StopIteration, csv.Error):
        logging.error(f"Could not parse command line: {line}")
        return output_file
    if not command_parts:
        return output_file
    # An indented line is the same command
    command_parts[0] = command_parts[0].strip()

    ref_moment = ref_moment.strip()
    sign = sign.strip()
    comment = ""

    if command_parts[0] == "TAKEPIC":
        camera_name, exposure, aperture, iso = command_parts[4:8]
        comment = command_parts[12] if len(command_parts) > 12 else ""
        command = "take_picture"
    elif command_parts[0] == "take_picture":
        camera_name, exposure, aperture, iso = command_parts[4:8]
        comment = command_parts[8] if len(command_parts) > 8 else ""
        command = "take_picture"
    elif command_parts[0] == "take_burst":
        camera_name, exposure, aperture, iso, number_of_pictures = command_parts[4:9]
        comment = command_parts[9] if len(command_parts) > 9 else ""
        command = "take_burst"
    elif command_parts[0] == "TAKEBST":
        camera_name, exposure, aperture, iso, number_of_pictures = command_parts[4:9]
        comment = command_parts[12] if len(command_parts) > 12 else ""
        command = "take_burst"
    elif command_parts[0] == "take_bracket":
        camera_name, exposure, aperture, iso, bracket = command_parts[4:9]
        comment = command_parts[9] if len(command_parts) > 9 else ""
        command = "take_bracket"
    elif command_parts[0] == "TAKEBKT":
        camera_name, exposure, aperture, iso = command_parts[4:8]
        comment = command_parts[12] if len(command_parts) > 12 else ""
        bracket = ""  # Will need to be set elsewhere
        command = "take_bracket"
    elif command_parts[0] == "prepare_camera":
        camera_name, exposure, aperture, iso, mode = command_parts[4:9]
        comment = command_parts[9] if len(command_parts) > 9 else ""
        command = "prepare_camera"
    elif command_parts[0] == "take_hdr":
        camera_name, exposure, aperture, iso, stops = command_parts[4:9]
        # Optional HDR sequence before the description (which is always last)
        hdr_sequence = command_parts[9] if len(command_parts) > 10 else ""
        comment = command_parts[-1] if len(command_parts) > 9 else ""
        command = "take_hdr"
    elif command_parts[0] == "sync_cameras":
        comment = command_parts[4] if len(command_parts) > 4 else ""
        command = "sync_cameras"
    elif command_parts[0] == "voice_prompt":
        sound_file = command_parts[4] if len(command_parts) > 4 else ""
        comment = command_parts[5] if len(command_parts) > 5 else ""
        command = "voice_prompt"
    elif command_parts[0] == "command":
        to_execute = command_parts[4] if len(command_parts) > 4 else ""
        comment = command_parts[5] if len(command_parts) > 5 else ""
        command = "command"
    elif command_parts[0] in HARDWARE_COMMANDS:
        # Relay commands take a variable number of arguments (none, a duration,
        # a duration and an interval), always followed by the description.
        command = command_parts[0]
        hardware_args = [part.strip() for part in command_parts[4:-1]] if len(command_parts) > 4 else []
        comment = command_parts[-1] if len(command_parts) > 4 else ""
    elif command_parts[0] == "PLAY":
        sound_file = command_parts[4] if len(command_parts) > 4 else ""
        comment = command_parts[12] if len(command_parts) > 12 else ""
        sound_file, _ = sound_file.upper().split('.')
        # Handle all sound files.
        if sound_file == "FILTERS_OFF":
            sound_file = "C2_IN_20_SECONDS"
        elif sound_file == "MAX_ECLIPSE":
            sound_file = "MAX"
        elif sound_file == "FILTERS_ON":
            sound_file = "FILTERS_ON"
        else:
            sound_file = ref_moment + "_IN_" + sound_file
        command = "voice_prompt"
    else:
        # A dropped line must never be silent: an unrecognised command in an
        # eclipse script means those moments simply do not fire, and that has
        # to be visible at load time, not discovered on the card afterwards.
        logging.warning("Script command %r is not recognised — this line will "
                        "NOT run: %s", command_parts[0], line.strip())
        return output_file

    # Remove the double quote from the comment
    comment = comment.replace('"', '')
    # print(command, comment)
    # Write the take_picture command to the output file.
    if command == "take_picture":
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {camera_name.strip()}, {exposure.strip()}, {aperture.strip()}, {iso.strip()}, \"{comment.strip()+extra_comment}\"\n")
    elif command == "take_burst":
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {camera_name.strip()}, {exposure.strip()}, {aperture.strip()}, {iso.strip()}, {number_of_pictures.strip()}, \"{comment.strip()+extra_comment}\"\n")
    elif command == "take_bracket":
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {camera_name.strip()}, {exposure.strip()}, {aperture.strip()}, {iso.strip()}, {bracket.strip()}, \"{comment.strip()+extra_comment}\"\n")
    elif command == "prepare_camera":
        # A bracket is quoted, as for take_bracket
        mode = mode.strip()
        mode = mode if mode.lower() in ("single", "burst") else f'"{mode}"'
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {camera_name.strip()}, {exposure.strip()}, {aperture.strip()}, {iso.strip()}, {mode}, \"{comment.strip()+extra_comment}\"\n")
    elif command == "take_hdr":
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {camera_name.strip()}, {exposure.strip()}, {aperture.strip()}, {iso.strip()}, {stops.strip()}, "
            + (f"{hdr_sequence.strip()}, " if hdr_sequence.strip() else "")
            + f"\"{comment.strip()+extra_comment}\"\n")
    elif command == "sync_cameras":
        output_file.write(f"{command}, {ref_moment}, {sign}, {time_delta}, \"{comment.strip()+extra_comment}\"\n")
    elif command == "voice_prompt":
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {sound_file.strip()}, \"{comment.strip()+extra_comment}\"\n")
    elif command == "command":
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {to_execute.strip()}, \"{comment.strip()+extra_comment}\"\n")
    elif command in HARDWARE_COMMANDS:
        fields = "".join(f"{arg}, " for arg in hardware_args)
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {fields}\"{comment.strip()+extra_comment}\"\n")

    while True:
        s = output_file.readline()
        if s == '':
            break
        print(s.strip())

    return output_file


def display1_10th_second(time_delta):
    # Fixed-point, so that float noise (0.7 * 3 = 2.0999999999999996) does not
    # lose a tenth and a tiny value is not written as 1e-05
    whole, fraction = f"{abs(float(time_delta)):.6f}".split('.')
    time_delta = str(timedelta(seconds=int(whole))) + "." + fraction[0]
    # Add a 0 if the time delta is less than 10 seconds.
    if time_delta.count(':') == 1:
        time_delta = "0" + time_delta
    return _get_delta_datetime(time_delta)


def _get_delta_datetime(delta: str) -> str:
    """ Calculate the time delta (with an accuracy of 1/10 of a seconds).

        Args:
            - delta (str): Time delta in the Solar Eclipse Maestro format (MM:SS.s or HH:MM:SS.s)

        Returns: String with the time delta in HH:MM:SS.s format
    """
    delta = delta.strip()
    if delta.count(":") == 1:
        # Check if delta contains a .
        if delta.count('.') == 1:
            delta_datetime = datetime.strptime(delta, "%M:%S.%f")
        else:
            delta_datetime = datetime.strptime(delta, "%M:%S")
    else:
        if delta.count('.') == 1:
            delta_datetime = datetime.strptime(delta, "%H:%M:%S.%f")
        else:
            delta_datetime = datetime.strptime(delta, "%H:%M:%S")
    return delta_datetime.strftime('%H:%M:%S.%f')[:-5]

def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _skip_loop_body(input_file, end_marker: str) -> None:
    """Read up to and including the line that ends a loop (or to the end of the file)."""
    line = input_file.readline()
    while line and not line.strip().startswith(end_marker):
        line = input_file.readline()


def convert_script(filename, reference_moments) -> io.StringIO:
    """
    Converts the input file from Solar Eclipse Maestro to a file that is readable by Solar Eclipse Workbench.

    A line that cannot be read is logged and left out; the rest of the script is converted.

    Returns: The converted script.
    """
    # utf-8-sig: a byte order mark (Windows Notepad) would otherwise be part of the first command name
    with open(filename, 'r', encoding='utf-8-sig', errors='replace') as input_file:
        return _convert_lines(input_file, reference_moments)


def _convert_lines(input_file, reference_moments) -> io.StringIO:
    output_file = io.StringIO()

    while True:
        line = input_file.readline()
        if not line:
            break
        # Drop empty lines and comments (starting with #)
        
        stripped_line = line.lstrip()
        
        if not stripped_line or stripped_line.startswith("#"):
            continue

        if not line.startswith('#') and not len(line) == 0: 
            # FOR loops in the Solar Eclipse Maestro scripts
            if line.startswith('FOR'):
                for_parts = next(csv.reader([line], skipinitialspace=True))
                for_type = for_parts[1] if len(for_parts) > 1 else ""
                direction = for_parts[2] if len(for_parts) > 2 else "1"
                interval = for_parts[3] if len(for_parts) > 3 else "0"
                number_of_steps = for_parts[4] if len(for_parts) > 4 else "1"
                
                if for_type == '(INTERVALOMETER)':
                    line = input_file.readline()
                    # Stop at the end of the file too: without ENDFOR this loop never ended
                    while line and not line.strip().startswith('ENDFOR'):
                        if _is_blank_or_comment(line):
                            line = input_file.readline()
                            continue
                        try:
                            if direction == "0":
                                # If direction is 0, count from high to low.
                                delta_sign = -1
                                start = int(number_of_steps)
                                stop = 0
                                step = -1
                            else:
                                # If direction is 1, count from low to high.
                                delta_sign = +1
                                start = 1
                                stop = int(number_of_steps) + 1
                                step = 1

                            iteration = 1
                            for i in range(start, stop, step):
                                line_parts = next(csv.reader([line], skipinitialspace=True))
                                ref_moment = line_parts[1] if len(line_parts) > 1 else ""
                                before_after = line_parts[2] if len(line_parts) > 2 else "+"
                                delta = line_parts[3] if len(line_parts) > 3 else "0:00:00.0"

                                # Some of the time deltas in the Solar Eclipse Maestro scripts are MM:SS.s, some
                                # HH:MM:SS.s, with or without the tenths
                                delta_datetime = datetime.strptime(_get_delta_datetime(delta), "%H:%M:%S.%f")
                                if before_after.strip() == "+":
                                    sign = 1
                                else:
                                    sign = -1
                                # Get the time delta per step in seconds, with its tenths
                                delta = timedelta(
                                    hours=delta_datetime.hour, minutes=delta_datetime.minute,
                                    seconds=delta_datetime.second, microseconds=delta_datetime.microsecond
                                    ).total_seconds() * sign
                                # Calculate the total time delta
                                time_delta = delta + delta_sign * ((i - 1) * float(interval))
                                if time_delta < 0:
                                    sign = "-"
                                else:
                                    sign = "+"
                                # Make sure to display 1/10 of a second.
                                time_delta = display1_10th_second(time_delta)
                                extra_comment = f" (Iter. {iteration})"

                                output_file = convert_command(line, ref_moment, sign, time_delta, extra_comment,
                                                              output_file)
                                iteration = iteration + 1
                        except (ValueError, IndexError, csv.Error, StopIteration) as e:
                            logging.warning("Script line in a FOR loop cannot be read (%s) — this line will NOT "
                                            "run: %s", e, line.strip())

                        line = input_file.readline()
                    if not line:
                        logging.warning("FOR loop without ENDFOR: the loop runs to the end of the script")
            elif line.startswith('for'):
                for_parts = next(csv.reader([line], skipinitialspace=True))
                start = for_parts[1].strip() if len(for_parts) > 1 else ""
                stop = for_parts[2].strip() if len(for_parts) > 2 else ""
                interval = for_parts[3] if len(for_parts) > 3 else 10
                start_delta = for_parts[4] if len(for_parts) > 4 else "0"
                stop_delta = for_parts[5] if len(for_parts) > 5 else "0"
                
                timings = reference_moments

                try:
                    interval_s = float(interval)
                    start_offset = timedelta(seconds=float(start_delta))
                    stop_offset = timedelta(seconds=float(stop_delta))
                except ValueError as e:
                    problem = f"its interval and offsets must be numbers ({e})"
                else:
                    problem = None if interval_s > 0 else "its interval must be more than 0 s"
                if problem is None and not (start in timings and stop in timings):
                    problem = (f"this eclipse has no {start if start not in timings else stop} "
                               f"(for loops need C1, C2, C3, C4, MAX, or END as reference moments)")
                if problem is not None:
                    # Used to end the application (exit()) here, schedule and all
                    logging.warning("The for loop %s will NOT run: %s", line.strip(), problem)
                    _skip_loop_body(input_file, 'endfor')
                    continue

                # start should be C1, C2, C3, C4, MAX, or END
                # stop should be C1, C2, C3, C4, MAX, or END
                # eclipse_type should be Partial, Annular, Total, or Hybrid
                start_time = timings[start].time_utc + start_offset
                stop_time = timings[stop].time_utc + stop_offset

                # Or just using the step size and stop when the stop moment is reached
                line = input_file.readline()
                # Stop at the end of the file too: without endfor this loop never ended
                while line and not line.strip().startswith('endfor'):
                    if _is_blank_or_comment(line):
                        line = input_file.readline()
                        continue
                    iteration = 1
                    current_time = start_time
                    while current_time < stop_time:
                        # Get the total time delta in seconds.
                        delta = (current_time - timings[start].time_utc).total_seconds()
                        if delta < 0:
                            sign = "-"
                        else:
                            sign = "+"
                        # Make sure to display 1/10 of a second.
                        time_delta = display1_10th_second(delta)

                        extra_comment = f" (Iter. {iteration})"

                        output_file = convert_command(line, start, sign, time_delta, extra_comment, output_file)

                        current_time = current_time + timedelta(seconds=interval_s)
                        iteration = iteration + 1

                    line = input_file.readline()
                if not line:
                    logging.warning("for loop without endfor: the loop runs to the end of the script")
            else:
                try:
                    # Use CSV parsing to handle quoted fields with commas
                    line_parts = next(csv.reader([line], skipinitialspace=True))
                    if len(line_parts) >= 4:
                        ref_moment = line_parts[1]
                        sign = line_parts[2]
                        delta = line_parts[3]
                        time_delta = _get_delta_datetime(delta)

                        output_file = convert_command(line, ref_moment, sign, time_delta, "", output_file)
                    else:
                        logging.info("Skipping line in script (not enough fields): " + line.strip())
                except (ValueError, csv.Error, StopIteration) as e:
                    logging.warning(f"Skipping line in script: {line.strip()} (error: {e}) — this line will NOT run")

    return output_file
