from enum import Enum
from pathlib import Path
from pydub import AudioSegment
from pydub.playback import play

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

def voice_prompt(notification: str) -> None:
    """ Voice prompt of the given notification.

    In the current implementation, the default voice from your system settings will be used.

    Args:
        - notification: Notification
    """
    SOUND_PATH = Path(__file__).parent.resolve() / ".." / ".." / "sound"
    song = AudioSegment.from_wav(str(SOUND_PATH) + "/" + Notifications[notification.lstrip()].value)
    play(song)


def main():
    # Example
    voice_prompt("C1_IN_40_SECONDS")


if __name__ == "__main__":
    main()
