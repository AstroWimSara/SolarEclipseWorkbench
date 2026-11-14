"""A simulated clock for the calibration and the centring: waiting takes no time.

The calibration and the centring time their slews, let the mount settle and
give up on a sun that is not found after some seconds.  With this clock
(centring.Clock's interface) every wait moves the simulated time on at once,
so a test of a calibration of minutes takes a fraction of a second, and the
timings are exact instead of a little longer than asked.

Everything that tells the time must use the same clock: the Calibrator or
Centrer (``clock=``), the fake mount timing its slews, and the simulated
camera stamping its frames (``monotonic=clock.monotonic``).
"""
import threading


class FakeClock:
    """Simulated monotonic time that only moves when something waits."""

    def __init__(self, start: float = 1000.0):
        self.now = start
        self._lock = threading.RLock()
        self._timers: list = []         # (when, callback), run once the time passes ``when``

    def monotonic(self) -> float:
        with self._lock:
            return self.now

    def advance(self, seconds: float) -> None:
        """Move the time on, running the callbacks that fall due on the way, in order."""
        with self._lock:
            end = self.now + max(0.0, seconds)
            while True:
                due = [timer for timer in self._timers if timer[0] <= end]
                if not due:
                    break
                timer = min(due, key=lambda t: t[0])
                self._timers.remove(timer)
                self.now = max(self.now, timer[0])
                timer[1]()
            self.now = end

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def wait(self, event: threading.Event, seconds: float) -> bool:
        """As Event.wait: returns at once when the event is set, else after ``seconds`` of simulated time."""
        if event.is_set():
            return True
        self.advance(seconds)
        return event.is_set()

    def call_later(self, seconds: float, callback) -> None:
        """Call ``callback`` once the simulated time has moved ``seconds`` on (as threading.Timer)."""
        with self._lock:
            self._timers.append((self.now + seconds, callback))
