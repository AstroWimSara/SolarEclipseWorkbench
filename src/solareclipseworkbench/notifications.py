import subprocess
import sys
from difflib import get_close_matches
from enum import Enum
from pathlib import Path
from typing import Optional

if sys.platform != "darwin":
    from playsound3 import playsound

SOUND_PATH = Path(__file__).parent.resolve() / "sound"

class Notifications(str, Enum):
    """ Enumeration of notifications that will be used for the voice prompt."""

    C1_IN_60_SECONDS = "c1_in_60_seconds.wav"
    C1_IN_40_SECONDS = "40_seconds.wav"
    C1_IN_30_SECONDS = "30_seconds.wav"
    C1_IN_20_SECONDS = "20_seconds.wav"
    C1_IN_15_SECONDS = "15.wav"
    C1_IN_10_SECONDS = "10.wav"
    C1_IN_5_SECONDS = "5.wav"
    C1_IN_4_SECONDS = "4.wav"
    C1_IN_3_SECONDS = "3.wav"
    C1_IN_2_SECONDS = "2.wav"
    C1_IN_1_SECOND = "1.wav"
    C1 = "c1.wav"
    C2_IN_50_MINUTES = "c2_in_50_minutes.wav"
    C2_IN_40_MINUTES = "c2_in_40_minutes.wav"
    C2_IN_30_MINUTES = "c2_in_30_minutes.wav"
    C2_IN_25_MINUTES = "c2_in_25_minutes.wav"
    C2_IN_20_MINUTES = "c2_in_20_minutes.wav"
    C2_IN_15_MINUTES = "c2_in_15_minutes.wav"
    C2_IN_10_MINUTES = "c2_in_10_minutes.wav"
    C2_IN_6_MINUTES = "c2_in_6_minutes.wav"
    C2_IN_5_MINUTES = "c2_in_5_minutes.wav"
    C2_IN_4_MINUTES = "c2_in_4_minutes.wav"
    C2_IN_2_MINUTES = "c2_in_2_minutes.wav"
    C2_IN_90_SECONDS = "c2_in_90_seconds.wav"
    C2_IN_60_SECONDS = "c2_in_60_seconds.wav"
    C2_IN_40_SECONDS = "c2_in_40_seconds.wav"
    C2_IN_30_SECONDS = "c2_in_30_seconds.wav"
    C2_IN_20_SECONDS = "c2_in_20_seconds.wav"
    C2_IN_15_SECONDS = "15.wav"
    C2_IN_10_SECONDS = "10.wav"
    C2_IN_5_SECONDS = "5.wav"
    C2_IN_4_SECONDS = "4.wav"
    C2_IN_3_SECONDS = "3.wav"
    C2_IN_2_SECONDS = "2.wav"
    C2_IN_1_SECOND = "1.wav"
    C2 = "c2.wav"
    C2_PLUS_30_SECONDS = "c2_plus_30_seconds.wav"
    MAX_IN_10_SECONDS = "max_in_10_seconds.wav"
    MAX_IN_5_SECONDS = "5.wav"
    MAX_IN_4_SECONDS = "4.wav"
    MAX_IN_3_SECONDS = "3.wav"
    MAX_IN_2_SECONDS = "2.wav"
    MAX_IN_1_SECOND = "1.wav"
    MAX = "max.wav"
    C3_IN_45_SECONDS = "c3_in_45_seconds.wav"
    C3_IN_20_SECONDS = "c3_in_20_seconds.wav"
    C3_IN_15_SECONDS = "15.wav"
    C3_IN_10_SECONDS = "10.wav"
    C3_IN_8_SECONDS = "c3_in_8_seconds.wav"
    C3_IN_5_SECONDS = "5.wav"
    C3_IN_4_SECONDS = "4.wav"
    C3_IN_3_SECONDS = "3.wav"
    C3_IN_2_SECONDS = "2.wav"
    C3_IN_1_SECOND = "1.wav"
    C3_PLUS_2_SECONDS = "c3_plus_2_seconds.wav"
    C3_PLUS_10_SECONDS = "c3_plus_10_seconds.wav"
    C3_PLUS_15_SECONDS = "c3_plus_15_seconds.wav"
    FILTERS_ON = "filters_on.wav"
    C3_PLUS_25_SECONDS = "c3_plus_25_seconds.wav"
    C3_PLUS_45_SECONDS = "c3_plus_45_seconds.wav"
    C3_PLUS_1_MINUTE = "c3_plus_1_minute.wav"
    C3_PLUS_2_MINUTES = "c3_plus_2_minutes.wav"
    C4_IN_60_SECONDS = "c4_in_60_seconds.wav"
    C4_IN_40_SECONDS = "40_seconds.wav"
    C4_IN_30_SECONDS = "30_seconds.wav"
    C4_IN_20_SECONDS = "20_seconds.wav"
    C4_IN_15_SECONDS = "15.wav"
    C4_IN_10_SECONDS = "10.wav"
    C4_IN_5_SECONDS = "5.wav"
    C4_IN_4_SECONDS = "4.wav"
    C4_IN_3_SECONDS = "3.wav"    
    C4_IN_2_SECONDS = "2.wav"   
    C4_IN_1_SECOND = "1.wav"
    C4 = "c4.wav"


def check_notification(notification: str) -> Optional[str]:
    """ Check that the given notification can actually be played.

    Voice prompts are only resolved when the job fires, so a typo in a script
    would otherwise surface as a KeyError in the middle of the eclipse, with the
    prompt silently missing.  Call this while the script is being loaded so the
    problem is visible while there is still time to fix it.

    Args:
        - notification: Notification name, as written in the script

    Returns: None if the notification resolves to an existing sound file,
             otherwise a message explaining what is wrong.
    """
    name = notification.strip()
    if not name:
        return "voice prompt has no notification name"

    try:
        sound_file = SOUND_PATH / Notifications[name].value
    except KeyError:
        message = f'unknown voice prompt "{name}"'
        close = get_close_matches(name, [item.name for item in Notifications], n=3)
        if close:
            message += " — did you mean " + ", ".join(close) + "?"
        return message

    if not sound_file.is_file():
        return f'voice prompt "{name}" maps to {sound_file.name}, which is missing from {SOUND_PATH}'

    return None


def voice_prompt(notification: str) -> None:
    """ Voice prompt of the given notification.

    Args:
        - notification: Notification
    """

    sound_file = str(SOUND_PATH) + "/" + Notifications[notification.lstrip()].value
    if sys.platform == "darwin":
        subprocess.run(["afplay", sound_file], check=True)
    else:
        playsound(sound_file)


def main():
    # Example
    voice_prompt("C1_IN_40_SECONDS")


if __name__ == "__main__":
    main()
