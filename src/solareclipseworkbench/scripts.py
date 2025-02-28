import io
from datetime import datetime, timedelta

def convert_command(line, ref_moment, sign, time_delta, extra_comment, output_file) -> io.StringIO:
    # Split line into different variables, separated by commas.  Only use the first 4 variables.
    command = line.split(",")
    ref_moment = ref_moment.strip()
    sign = sign.strip()
    comment = ""

    if command[0] == "TAKEPIC":
        _, _, _, _, camera_name, exposure, aperture, iso, _, _, _, _, comment = line.split(",")
        command = "take_picture"
    elif command[0] == "take_picture":
        _, _, _, _, camera_name, exposure, aperture, iso, comment = line.split(",")
        command = "take_picture"
    elif command[0] == "take_burst":
        _, _, _, _, camera_name, exposure, aperture, iso, number_of_pictures, comment = line.split(",")
        command = "take_burst"
    elif command[0] == "TAKEBST":
        _, _, _, _, camera_name, exposure, aperture, iso, number_of_pictures, _, _, _, comment = line.split(",")
        command = "take_burst"
    elif command[0] == "take_bracket":
        _, _, _, _, camera_name, exposure, aperture, iso, bracket, comment = line.split(",")
        command = "take_bracket"
    elif command[0] == "TAKEBKT":
        _, _, _, _, camera_name, exposure, aperture, iso, _, _, _, _, comment = line.split(",")
        command = "take_bracket"
    elif command[0] == "sync_cameras":
        _, _, _, _, comment = line.split(",")
        command = "sync_cameras"
    elif command[0] == "voice_prompt":
        _, _, _, _, sound_file, comment = line.split(",")
        command = "voice_prompt"
    elif command[0] == "PLAY":
        _, _, _, _, sound_file, _, _, _, _, _, _, _, comment = line.split(",")
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
    elif command == "sync_cameras":
        output_file.write(f"{command}, {ref_moment}, {sign}, {time_delta}, \"{comment.strip()+extra_comment}\"\n")
    elif command == "voice_prompt":
        output_file.write(
            f"{command}, {ref_moment}, {sign}, {time_delta}, {sound_file.strip()}, \"{comment.strip()+extra_comment}\"\n")

    while True:
        s = output_file.readline()
        if s == '':
            break
        print(s.strip())

    return output_file


def display1_10th_second(time_delta):
    if str(time_delta).count('.') == 1:
        _, fraction = str(time_delta).split('.')
        time_delta = str(timedelta(seconds=abs(int(time_delta)))) + "." + fraction[0]
    else:
        time_delta = str(timedelta(seconds=abs(time_delta))) + ".0"
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

def convert_script(filename, reference_moments) -> io.StringIO:
    """
    Converts the input file from Solar Eclipse Maestro to a file that is readable by Solar Eclipse Workbench.

    Returns: None
    """    
    input_file = open(filename, 'r')
    output_file = io.StringIO()

    while True:
        line = input_file.readline()
        if not line:
            break
        # Drop empty lines and comments (starting with #)
        if not line.startswith('#') and not len(line) == 0: 
            # FOR loops in the Solar Eclipse Maestro scripts
            if line.startswith('FOR'):
                _, for_type, direction, interval, number_of_steps = line.split(",")
                if for_type == '(INTERVALOMETER)':
                    line = input_file.readline()
                    while not line.startswith('ENDFOR'):
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
                            _, ref_moment, before_after, delta, camera_name, exposure, aperture, iso, _, _, _, _, comment = line.split(",")
                            # Some of the time deltas in the Solar Eclipse Maestro scripts are MM:SS.s, some HH:MM:SS.s
                            if delta.count(":") == 1:
                                delta_datetime = datetime.strptime(delta, "%M:%S.%f")
                            else:
                                delta_datetime = datetime.strptime(delta, "%H:%M:%S.%f")
                            if before_after == "+":
                                sign = 1
                            else:
                                sign = -1
                            # Get the time delta per step in seconds.
                            delta = timedelta(
                                hours=delta_datetime.hour, minutes=delta_datetime.minute, seconds=delta_datetime.second
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

                            output_file = convert_command(line, ref_moment, sign, time_delta, extra_comment, output_file)
                            iteration = iteration + 1

                        line = input_file.readline()
            elif line.startswith('for'):
                _, start, stop, interval, start_delta, stop_delta = line.split(",")
                # Convert interval to float
                interval = int(interval)
                timings = reference_moments

                # start should be C1, C2, C3, C4, MAX, or END
                # stop should be C1, C2, C3, C4, MAX, or END
                # eclipse_type should be Partial, Annular, Total, or Hybrid
                if start in timings and stop in timings:
                    start_time = timings[start].time_utc + timedelta(seconds=float(start_delta))
                    stop_time = timings[stop].time_utc + timedelta(seconds=float(stop_delta))

                    # Or just using the step size and stop when the stop moment is reached
                    line = input_file.readline()
                    while not line.startswith('endfor'):
                        iteration = 1
                        current_time = start_time
                        while current_time < stop_time:
                            command, ref_moment, before_after, delta, _ = line.split(",", 4)
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

                            current_time = current_time + timedelta(seconds=interval)
                            iteration = iteration + 1

                        line = input_file.readline()
                else:
                    print ('for loops need C1, C2, C3, C4, MAX, or END as reference moments.')
                    exit()
            else:
                _, ref_moment, sign, delta, _ = line.split(",", 4)
                time_delta = _get_delta_datetime(delta)

                output_file = convert_command(line, ref_moment, sign, time_delta, "", output_file)

    return output_file


