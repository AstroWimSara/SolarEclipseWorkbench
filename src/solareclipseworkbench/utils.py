COMMANDS = {
    'voice_prompt': voice_prompt,
    'take_picture': take_picture
}
def start_scheduler():
    """ Start background scheduler and return it.

    Returns: Background scheduler that has been started.
    """

    scheduler = BackgroundScheduler()
    scheduler.start()

    return scheduler


def schedule_commands(filename: str, scheduler: BackgroundScheduler, reference_moments):
    """ Schedule commands as specified in the given file.

    Args:
        - filename: Name of the file in which the commands have been listed, scheduled relatively to the given
                    reference moments
        - scheduler: Background scheduler to use to schedule the commands
        - reference_moments: Dictionary with the reference moments (1st - 4th contact and maximum eclipse), with
                             respect to which the commands are scheduled

    Returns: Scheduler that is used to schedule the commands.
    """

    with open(filename, "r") as file:
        for cmd_str in file:
            print(cmd_str)
            interpret_cmd_str(scheduler, reference_moments, cmd_str)
