


import argparse


def main(input, output):
    inputfile = open(input, 'r')
    # TODO: Use readline() to be able to get all information for the for loops.
    lines = inputfile.readlines()
 
    count = 0

    for line in lines:
        count += 1
        if not line.startswith('#') and not len(line.strip()) == 0: 
            if (line.startswith('FOR')):
                print ("Start of FOR loop")
            print("Line{}: {}".format(count, line.strip()), len(line.strip()))


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
