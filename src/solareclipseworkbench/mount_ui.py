"""Widgets for the telescope mount: the N/S/E/W nudge panel.

The panel finds the mount in the hardware registry (where the `Mount` window
registers it), so it can sit in any window without being handed the mount, and
follows a mount that is connected or disconnected while it is shown.
"""

import math
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from solareclipseworkbench.hardware_registry import get_hardware
from solareclipseworkbench.mount import MountError

#: How often a held button renews its nudge.  Well below Nudger.HOLD_S, so the
#: mount keeps moving smoothly while the button is held.
RENEW_MS = 200

#: Settings key of the chosen nudge rate
RATE_SETTING = "mount/nudge_rate"

#: Arrows on the buttons, by direction
ARROWS = {"N": "▲ N", "S": "▼ S", "E": "E ▶", "W": "◀ W"}


def format_position(position: Optional[tuple]) -> str:
    """'RA 14h41m32s  Dec −15°41′17″' for (ra hours, dec degrees)."""
    if not position or None in position:
        return ""
    ra, dec = position
    # The INDI client keeps NaN for a number it could not read; round(NaN) raises, every refresh
    if not (math.isfinite(ra) and math.isfinite(dec)):
        return ""
    ra_s = round(ra * 3600) % (24 * 3600)
    sign = "−" if dec < 0 else "+"
    dec_s = round(abs(dec) * 3600)
    return (f"RA {ra_s // 3600:02d}h{ra_s // 60 % 60:02d}m{ra_s % 60:02d}s  "
            f"Dec {sign}{dec_s // 3600:02d}°{dec_s // 60 % 60:02d}′{dec_s % 60:02d}″")


def _settings() -> QSettings:
    return QSettings(str(Path.home() / ".SolarEclipseWorkbench.ini"), QSettings.Format.IniFormat)


class MountNudgePanel(QWidget):
    """A row with the nudge rate, the N/S/E/W buttons, Stop and the position of the mount.

    A button moves the mount for as long as it is held.  The mount stops by
    itself shortly after the button stops renewing the nudge, also when the
    release is never seen (see mount.Nudger).

    Args:
        - hide_when_absent: Hide the panel while no mount is connected (in the
                            Live View window); otherwise it is only disabled.
    """

    def __init__(self, parent: Optional[QWidget] = None, hide_when_absent: bool = False):
        super().__init__(parent)
        self._hide_when_absent = hide_when_absent
        self._mount = None
        self._held: Optional[str] = None

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Mount:"))
        self.rate_combo = QComboBox()
        self.rate_combo.setToolTip("Speed of the nudges.  The slowest is the guide rate.")
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        layout.addWidget(self.rate_combo)

        self.buttons = {}
        for direction in ("W", "N", "S", "E"):
            button = QPushButton(ARROWS[direction])
            button.setToolTip(f"Move the mount towards {direction} on the sky while the button is held.  "
                              "The picture may be turned or mirrored.")
            button.pressed.connect(lambda d=direction: self._press(d))
            button.released.connect(lambda d=direction: self._release(d))
            layout.addWidget(button)
            self.buttons[direction] = button

        self.stop_button = QPushButton("Stop")
        self.stop_button.setToolTip("Stop every motion of the mount now (a park as well).  Tracking goes on.")
        self.stop_button.clicked.connect(self._stop)
        layout.addWidget(self.stop_button)

        self.position_label = QLabel()
        layout.addWidget(self.position_label)
        layout.addStretch(1)
        self.setLayout(layout)

        self._renew_timer = QTimer(self)
        self._renew_timer.setInterval(RENEW_MS)
        self._renew_timer.timeout.connect(self._renew)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    # ------------------------------------------------------------- the mount

    def mount(self):
        """The connected mount, or None."""
        mount = get_hardware('mount')
        return mount if mount is not None and mount.connected else None

    def refresh(self) -> None:
        """Follow the mount being connected or disconnected, and show its position."""
        mount = self.mount()
        if mount is not self._mount:
            self._release(self._held)
            self._mount = mount
            self._fill_rates()
        present = mount is not None
        if self._hide_when_absent:
            self.setVisible(present)
        for widget in list(self.buttons.values()) + [self.stop_button, self.rate_combo]:
            widget.setEnabled(present)
        self.rate_combo.setEnabled(present and self.rate_combo.count() > 1)
        self.position_label.setText(format_position(mount.position()) if present else "No mount connected")

    def _fill_rates(self) -> None:
        self.rate_combo.blockSignals(True)
        self.rate_combo.clear()
        rates = self._mount.slew_rates() if self._mount is not None else []
        for name, label in rates:
            self.rate_combo.addItem(label if label == name else f"{label} ({name})", name)
        if not rates:
            self.rate_combo.addItem("driver default", None)
        saved = _settings().value(RATE_SETTING, "", type=str)
        index = self.rate_combo.findData(saved) if saved else -1
        self.rate_combo.setCurrentIndex(index if index >= 0 else 0)     # the slowest by default
        self.rate_combo.blockSignals(False)

    def rate(self) -> Optional[str]:
        return self.rate_combo.currentData()

    def _on_rate_changed(self, _index: int) -> None:
        if self.rate():
            _settings().setValue(RATE_SETTING, self.rate())

    # --------------------------------------------------------------- buttons

    def _press(self, direction: str) -> None:
        if self._mount is None:
            return
        self._held = direction
        self._renew()
        self._renew_timer.start()

    def _renew(self) -> None:
        if self._mount is None or self._held is None:
            self._renew_timer.stop()
            return
        try:
            self._mount.nudger.hold(self._held, self.rate())
        except MountError:
            self._renew_timer.stop()

    def _release(self, direction: Optional[str]) -> None:
        self._renew_timer.stop()
        if direction is None or direction != self._held:
            return
        self._held = None
        if self._mount is not None:
            self._mount.nudger.release(direction)

    def _stop(self) -> None:
        self._release(self._held)
        if self._mount is not None:
            self._mount.nudger.abort()

    def hideEvent(self, event):
        # A button held while the window closes must not keep the mount moving
        self._release(self._held)
        super().hideEvent(event)
