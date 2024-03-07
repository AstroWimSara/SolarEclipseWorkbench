import argparse
from datetime import datetime, timedelta


def main(input: str, output: str) -> None:
    """
    Converts the input file from Solar Eclipse Maestro to a file that is readable by Solar Eclipse Workbench.
    
    Args:
        - input (str): Path of the Solar Eclipse Maestro input file
        - output (str): Path of the output file

    Returns: None
    """    
    inputfile = open(input, 'r')
    outputfile = open(output, 'w')

    while True:
        line = inputfile.readline()
        if not line:
            break
        # Drop empty lines and comments (starting with #)
        if not line.startswith('#') and not len(line) == 0: 
            # FOR loops in the Solar Eclipse Maestro scripts
            if line.startswith('FOR'):
                _, _, direction, interval, number_of_steps = line.split(",")
                line = inputfile.readline()
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
                        command = line.split(",")
                        if (command[0] == "TAKEPIC"):
                            command = "take_picture"
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
                            time_delta = delta + delta_sign * (((i - 1) * float(interval)))
                            if time_delta < 0:
                                sign = "-"
                            else:
                                sign = "+"
                            # Make sure to display 1/10 of a second.
                            if str(time_delta).count('.') == 1:
                                _, fraction = str(time_delta).split('.')
                                time_delta = str(timedelta(seconds=abs(int(time_delta)))) + "." + fraction[0]
                            else:
                                time_delta = str(timedelta(seconds=abs(time_delta))) + ".0"
                            # Write the take_picture command to the output file.
                            outputfile.write(f"{command}, {ref_moment}, {sign}, {time_delta}, {camera_name}, {exposure}, {aperture}, {iso}, \"{comment.strip()} (Iter. {iteration})\"\n")
                        iteration = iteration + 1

                    line = inputfile.readline()

            command = line.split(",")
            if command[0] == "PLAY":
                _, ref_moment, before_after, delta, sound_file, _, _, _, _, _, _, _, comment = line.split(",")
                delta_datetime = _get_delta_datetime(delta)
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
                # Write the voice_prompt command to the output file.
                comment = comment.strip('\n')
                outputfile.write(f"voice_prompt, {ref_moment}, {before_after}, {delta_datetime}, {sound_file}, \"{comment}\"\n")
            elif command[0] == "TAKEPIC":
                _, ref_moment, before_after, delta, camera_name, exposure, aperture, iso, _, _, _, _, comment = line.split(",")
                delta_datetime = _get_delta_datetime(delta)
                # Write the take_picture command to the output file.
                outputfile.write(f"take_picture, {ref_moment}, {before_after}, {delta_datetime}, {camera_name}, {exposure}, {aperture}, {iso}, \"{comment.strip()}\"\n")
    outputfile.close()


    """ Calculate the time delta (with an accuracy of 1/10 of a seconds).

    Args:
        - delta (str): Time delta in the Solar Eclipse Maestro format (MM:SS.s or HH:MM:SS.s)

    Returns: String with the time delta in HH:MM:SS.s format
    """
def _get_delta_datetime(delta: str) -> str:
    if delta.count(":") == 1:
        delta_datetime = datetime.strptime(delta, "%M:%S.%f")
    else:
        delta_datetime = datetime.strptime(delta, "%H:%M:%S.%f")
    return delta_datetime.strftime('%H:%M:%S.%f')[:-5]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="convert_SEM_files")
    parser.add_argument(
        "-i",
        "--input",
        help="File from Solar Eclipse Maestro to convert",
        default=False,
        required=True,
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Converted file to use in Solar Eclipse Workbench",
        default=False,
        required=True,
    )
    args = parser.parse_args()

    main(args.input, args.output)
