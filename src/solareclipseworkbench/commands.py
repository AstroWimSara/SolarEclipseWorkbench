import logging
import subprocess

def execute_command(command: str) -> None:
    """Start a command in the background (non-blocking).

    This launches the given shell command asynchronously and returns immediately.
    Any stdout/stderr is discarded so the background process cannot block due to
    filled pipes. Errors starting the process are logged but not raised to avoid
    blocking the scheduler.

    Args:
        - command: Command to execute, as a string. The command should be a valid bash command.
    """

    logging.info(f"Starting background command: {command}")

    try:
        # Start the process without waiting. Redirect output to DEVNULL so it
        # cannot block the parent, and use start_new_session to decouple the
        # child from the parent's process group on POSIX systems.
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logging.info(f"Background command started, pid={getattr(proc, 'pid', '<unknown>')}")
    except Exception as e:
        logging.error(f"Failed to start background command: {e}")
        # Do not raise — keep scheduler and UI responsive even if the command fails to start.
        return


