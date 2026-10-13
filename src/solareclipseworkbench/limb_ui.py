"""Baily's beads, drawn for the observing location.

The true lunar limb against the Sun's limb, with the arcs where sunlight still
gets through filled in, and a slider over the seconds either side of a contact
so the beads can be watched forming and going out.  As the last bead goes the
solar limb sits tangent to the deepest valley and nothing is lit, which is the
arc calculation made visible.

The window also states how large the correction is and whether it is being
applied, so an implausible one at an untested location is visible before it is
trusted.  It is opened with the "Baily's beads" button in the toolbar.

Ported from Mike Rosseel's fork (fuji-on-main), where it is a dock panel.
"""

import logging
import threading

import numpy as np
from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QSlider,
                             QVBoxLayout, QWidget)

from solareclipseworkbench.limb_correction import (K2, EARTH_RADIUS_KM, is_enabled,
                                                   solar_limb_reach, solve_limb)

# How far either side of a contact the slider reaches.
SLIDER_RANGE_S = 8.0
SLIDER_STEPS = 320

# Live only draws the run-up to the beads.  Earlier than this the Sun's limb is
# far outside the Moon and, at these exaggerations, fills the frame with a slab
# of yellow that reads as a sun receding rather than beads approaching.
LIVE_APPROACH_S = 25.0

PROFILE_COLOUR = QColor(150, 120, 200)
SUN_COLOUR = QColor(240, 170, 60)
BEAD_COLOUR = QColor(255, 220, 90)
MEAN_COLOUR = QColor(130, 130, 130)


def beads_icon(size=32):
    """A diamond ring, drawn rather than shipped: no icon in img/ suits this."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.12
    diameter = size - 2 * margin

    # The corona, then the Moon covering it, offset just enough to leave a bead.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(SUN_COLOUR)
    painter.drawEllipse(QPointF(size / 2, size / 2), diameter / 2, diameter / 2)

    painter.setBrush(QColor(30, 30, 36))
    painter.drawEllipse(QPointF(size / 2 - size * 0.04, size / 2),
                        diameter / 2 * 0.94, diameter / 2 * 0.94)

    painter.setBrush(BEAD_COLOUR)
    painter.drawEllipse(QPointF(size / 2 + diameter / 2 * 0.86, size / 2 - size * 0.06),
                        size * 0.11, size * 0.11)
    painter.end()
    return QIcon(pixmap)


def contact_hours(solution, contact):
    """The contact the slider is centred on: the C2 or C3 shown in the reference moments.

    That is the contact-point corrected time, so "C2 +0.00 s" here is the same
    instant as the C2 row.  The last bead goes at the inner edge of the bead
    window instead, a second or two away.
    """
    point = solution.c2_point if contact == "C2" else solution.c3_point
    if point is None:
        point = solution.c2_limb if contact == "C2" else solution.c3_limb
    return point


def _seconds(value):
    return "-" if value is None else f"{value:.1f}"


class BeadsView(QWidget):
    """The profile itself: position angle across, limb height up."""

    def __init__(self, solution):
        super().__init__()
        self.solution = solution
        self.contact = "C2"
        self.offset_s = 0.0
        self.mode = "profile"
        self.exaggeration = 50.0
        self.live_hours = None
        self.countdown = None
        # Only needs to be wide enough to draw a limb profile
        self.setMinimumSize(240, 140)

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def set_exaggeration(self, factor):
        self.exaggeration = float(factor)
        self.update()

    def set_contact(self, contact):
        self.contact = contact
        self.offset_s = 0.0
        self.update()

    def set_offset(self, offset_s):
        self.offset_s = offset_s
        self.update()

    def moment_hours(self):
        if self.live_hours is not None:
            return self.live_hours
        return contact_hours(self.solution, self.contact) + self.offset_s / 3600.0

    def set_countdown(self, text):
        """Show a countdown instead of the profile, or None to draw again."""
        self.countdown = text
        self.update()

    def set_live_hours(self, hours):
        """Follow the clock, or None to go back to the slider."""
        self.live_hours = hours
        self.update()

    def visible_angles(self, span_deg=40.0):
        """The arc worth drawing: centred on where the contact happens."""
        from solareclipseworkbench.limb_correction import contact_position_angle
        centre = contact_position_angle(self.solution.evaluate(self.moment_hours()))
        return centre - span_deg / 2.0, centre + span_deg / 2.0

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(18, 18, 22))

        solution = self.solution
        if solution is None:
            return

        if self.countdown is not None:
            font = painter.font()
            font.setPointSize(max(14, int(self.height() * 0.12)))
            painter.setFont(font)
            painter.setPen(QColor(170, 170, 185))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.countdown)
            return

        if self.mode == "preview":
            self._paint_preview(painter)
            return
        hours = self.moment_hours()
        elements = solution.evaluate(hours)

        low, high = self.visible_angles()
        angles = solution.angles
        # Work on the unwrapped window, so an arc straddling north still draws.
        shifted = (angles - low) % 360.0
        inside = shifted <= (high - low)
        if not inside.any():
            return

        window_angles = shifted[inside]
        order = np.argsort(window_angles)
        window_angles = window_angles[order]
        heights_km = solution.heights_km[inside][order]

        from solareclipseworkbench.limb_correction import solar_limb_reach
        reach = solar_limb_reach(elements, angles)[inside][order]
        # Both curves as heights above k2, in km, then arcseconds.
        sun_km = (reach - K2) * EARTH_RADIUS_KM
        margin = sun_km - heights_km

        span_km = max(heights_km.max(), sun_km.max()) - min(heights_km.min(), sun_km.min())
        span_km = max(span_km, 1.0)
        low_km = min(heights_km.min(), sun_km.min()) - 0.1 * span_km
        high_km = max(heights_km.max(), sun_km.max()) + 0.1 * span_km

        left, right, top, bottom = 60, self.width() - 12, 12, self.height() - 34

        def to_x(angle):
            return left + (angle / (high - low)) * (right - left)

        def to_y(km):
            return bottom - (km - low_km) / (high_km - low_km) * (bottom - top)

        # Mean limb, k2.
        painter.setPen(QPen(MEAN_COLOUR, 1, Qt.PenStyle.DashLine))
        painter.drawLine(left, int(to_y(0.0)), right, int(to_y(0.0)))

        # Beads: where the Sun still shows past the true limb.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BEAD_COLOUR)
        lit = margin > 0.0
        if lit.any():
            run_start = None
            for index, is_lit in enumerate(lit):
                if is_lit and run_start is None:
                    run_start = index
                elif not is_lit and run_start is not None:
                    self._fill_bead(painter, window_angles, heights_km, sun_km,
                                    run_start, index, to_x, to_y)
                    run_start = None
            if run_start is not None:
                self._fill_bead(painter, window_angles, heights_km, sun_km,
                                run_start, len(lit), to_x, to_y)

        self._draw_curve(painter, window_angles, heights_km, to_x, to_y, PROFILE_COLOUR, 2)
        self._draw_curve(painter, window_angles, sun_km, to_x, to_y, SUN_COLOUR, 1)

        painter.setPen(QColor(200, 200, 210))
        painter.drawText(left, bottom + 22,
                         f"position angle {low % 360:.0f}° to {high % 360:.0f}°")
        painter.drawText(left, top + 14,
                         f"{self.contact} {self.offset_s:+.2f} s     "
                         f"{int(lit.sum() and self._bead_count(lit))} beads")
        painter.setPen(PROFILE_COLOUR)
        painter.drawText(8, int(to_y(high_km)) + 20, "km")

    def _paint_preview(self, painter):
        """The Moon over the Sun, the way SEM draws it: polar, relief exaggerated.

        Real limb relief is about 0.2% of the lunar radius, so at true scale the
        beads are sub-pixel.  Exaggerating the departure from the mean limb --
        the same thing SEM does with its height exaggeration factor -- is what
        makes the shape of the contact legible.
        """
        solution = self.solution
        elements = solution.evaluate(self.moment_hours())
        angles = solution.angles

        mean_km = K2 * EARTH_RADIUS_KM
        base = min(self.width(), self.height()) * 0.42
        centre = QPointF(self.width() / 2, self.height() / 2)

        def radius(height_km):
            return base * (1.0 + self.exaggeration * height_km / mean_km)

        sun_km = (solar_limb_reach(elements, angles) - K2) * EARTH_RADIUS_KM
        # Away from the contact the Sun sits far inside the limb, and at this
        # exaggeration its radius would go negative and turn the polygon inside
        # out.  Clamp it just inside the deepest valley: any lower and the clamp
        # itself becomes visible as a small disc, any higher and it pokes out
        # where it should not.
        floor_km = solution.heights_km.min() - 0.02 * (solution.heights_km.max()
                                                       - solution.heights_km.min())
        sun_km = np.maximum(sun_km, floor_km)

        def polygon(heights):
            points = []
            for angle, height in zip(angles, heights):
                r = radius(height)
                # Position angle runs from north through east; screen y is down.
                theta = np.radians(angle)
                points.append(QPointF(centre.x() + r * np.sin(theta),
                                      centre.y() - r * np.cos(theta)))
            return QPolygonF(points)

        painter.setClipRect(self.rect())

        # Sunlight first, then the Moon over it: what is left showing is a bead.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BEAD_COLOUR)
        painter.drawPolygon(polygon(sun_km))

        painter.setBrush(QColor(24, 24, 30))
        painter.setPen(QPen(PROFILE_COLOUR, 1))
        painter.drawPolygon(polygon(solution.heights_km))

        # The mean limb, for scale.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(MEAN_COLOUR, 1, Qt.PenStyle.DashLine))
        painter.drawEllipse(centre, base, base)

        painter.setPen(QColor(200, 200, 210))
        painter.drawText(8, 16, f"{self.contact} {self.offset_s:+.2f} s")
        painter.drawText(8, self.height() - 8,
                         f"relief exaggerated {self.exaggeration:.0f}x")

    @staticmethod
    def _bead_count(lit):
        return int((lit & ~np.roll(lit, 1)).sum())

    @staticmethod
    def _draw_curve(painter, angles, values, to_x, to_y, colour, width):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(colour, width))
        polygon = QPolygonF([QPointF(to_x(a), to_y(v)) for a, v in zip(angles, values)])
        painter.drawPolyline(polygon)

    @staticmethod
    def _fill_bead(painter, angles, limb, sun, start, end, to_x, to_y):
        piece = list(range(start, end))
        points = [QPointF(to_x(angles[i]), to_y(sun[i])) for i in piece]
        points += [QPointF(to_x(angles[i]), to_y(limb[i])) for i in reversed(piece)]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BEAD_COLOUR)
        painter.drawPolygon(QPolygonF(points))


class BeadsPanel(QWidget):
    """Baily's beads, in a window of their own.

    Idle until it is told where and when the eclipse is.  Solving the limb
    profile costs a couple of seconds (and the first time it may download the
    profile), so it happens in the background, once per location or date rather
    than on every repaint.
    """

    # Emitted from the solver thread with (context, solution); delivered in the GUI thread
    solved = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Baily's beads")
        self.setWindowIcon(beads_icon(32))
        self.resize(640, 420)

        self.solution = None
        self._context = None
        self.solved.connect(self._on_solved)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.summary = QLabel("Corrections \u2014 set a location and a date")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.view = BeadsView(None)
        self.view.setMinimumHeight(150)
        layout.addWidget(self.view, 1)

        controls = QHBoxLayout()

        self.mode_box = QComboBox()
        self.mode_box.addItems(["Profile", "Preview"])
        self.mode_box.currentTextChanged.connect(
            lambda text: self.view.set_mode(text.lower()))
        controls.addWidget(self.mode_box)

        self.exaggeration_box = QComboBox()
        self.exaggeration_box.addItems(["10x", "25x", "50x", "100x"])
        self.exaggeration_box.setCurrentText("50x")
        self.exaggeration_box.currentTextChanged.connect(
            lambda text: self.view.set_exaggeration(float(text.rstrip("x"))))
        controls.addWidget(self.exaggeration_box)

        # Free scrubs the seconds around a contact; Live pins the picture to the
        # clock, which is what it should show while an eclipse is actually on.
        self.follow_box = QComboBox()
        self.follow_box.addItems(["Free", "Live"])
        self.follow_box.currentTextChanged.connect(self._on_follow)
        controls.addWidget(self.follow_box)

        self.contact_box = QComboBox()
        self.contact_box.addItems(["C2", "C3"])
        self.contact_box.currentTextChanged.connect(self._on_contact)
        controls.addWidget(self.contact_box)

        controls.addStretch(1)
        layout.addLayout(controls)

        # The slider gets its own row, so it stays wide enough to drag
        scrub = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-SLIDER_STEPS, SLIDER_STEPS)
        self.slider.setMinimumWidth(160)
        self.slider.valueChanged.connect(self._on_slider)
        scrub.addWidget(self.slider, 1)

        self.time_label = QLabel("-")
        scrub.addWidget(self.time_label)
        layout.addLayout(scrub)

        self._set_controls_enabled(False)

    def follow_live(self) -> None:
        """Pin the picture to the clock.

        Called when a script is loaded: from then on the panel should show what
        is happening rather than whatever second was last scrubbed to.  It is a
        starting position, not a lock - Free is still there for anybody who
        wants to look around during the partials.
        """
        if self.follow_box.currentText() != "Live":
            self.follow_box.setCurrentText("Live")

    def _set_controls_enabled(self, enabled):
        live = self.follow_box.currentText() == "Live"
        self.contact_box.setEnabled(enabled and not live)
        self.slider.setEnabled(enabled and not live)
        self.mode_box.setEnabled(enabled)
        self.exaggeration_box.setEnabled(enabled)
        self.follow_box.setEnabled(enabled)

    def set_context(self, eclipse_date, longitude, latitude, altitude):
        """Point the panel at a place and a date, and solve the limb there in the background."""
        context = (eclipse_date, longitude, latitude, altitude)
        if context == self._context:
            return
        self._context = context

        self.solution = None
        self.view.solution = None
        self._set_controls_enabled(False)
        self.summary.setText("Solving the lunar limb profile...")
        self.summary.setStyleSheet("")
        self.view.update()

        def solve():
            try:
                solution = solve_limb(eclipse_date, latitude, longitude, altitude)
            except Exception as exc:
                logging.warning("Could not solve the lunar limb profile: %s", exc)
                solution = None
            try:
                self.solved.emit(context, solution)
            except RuntimeError:
                pass    # The window was closed and deleted while solving

        threading.Thread(target=solve, daemon=True, name="BeadsSolver").start()

    def _on_solved(self, context, solution):
        """Show a finished solve, unless the place or date has changed since it started."""
        if context != self._context:
            return
        self.solution = solution
        self.view.solution = solution
        self._set_controls_enabled(solution is not None)
        self.slider.setValue(0)
        self.refresh()

    def refresh(self):
        """Redraw the summary, which depends on whether the correction is on."""
        mark = "\u2713" if is_enabled() else "\u2717"

        if self.solution is None:
            self.summary.setText(f"{mark} Corrections \u2014 no limb profile here")
            self.view.update()
            return

        solution = self.solution
        # The contact-point corrections, which are what the C2 and C3 rows show
        at_point = solution.c2_point is not None and solution.c3_point is not None
        c2 = solution.correction_seconds("C2", at_point=at_point)
        c3 = solution.correction_seconds("C3", at_point=at_point)
        text = (f"{mark} Corrections{'' if is_enabled() else ' (off)'}   limb "
                f"C2 {c2:+.1f}s   C3 {c3:+.1f}s   "
                f"beads {_seconds(solution.window_seconds('C2'))}/{_seconds(solution.window_seconds('C3'))}s   "
                f"totality {c3 - c2:+.1f}s")

        biggest = max(abs(c2), abs(c3))
        if biggest > 15.0:
            text += "   \u26a0 large, check the beads"

        self.summary.setText(text)
        self.summary.setStyleSheet("color: #e0a030;" if biggest > 15.0 else "")
        self._on_slider(self.slider.value())
        self.view.update()

    def is_live(self):
        return self.follow_box.currentText() == "Live"

    def _on_follow(self, _text):
        live = self.is_live()
        self.contact_box.setEnabled(not live and self.solution is not None)
        self.slider.setEnabled(not live and self.solution is not None)
        if not live:
            self.view.set_countdown(None)
            self.view.set_live_hours(None)
            self._on_slider(self.slider.value())

    def set_current_time(self, moment_utc):
        """Called on every clock tick; only does anything in Live mode.

        Outside totality there is no contact geometry to draw -- the Sun and
        Moon are nowhere near tangent, and the curves degenerate into nonsense --
        so say how far away it is rather than drawing it.
        """
        if self.solution is None or not self.is_live():
            return

        hours = self.solution.from_utc(moment_utc)
        solution = self.solution

        # Each bead window, plus a short run-up so they can be seen arriving.
        windows = [(solution.c2_limb - LIVE_APPROACH_S / 3600.0, solution.c2_limb, "C2"),
                   (solution.c3_limb, solution.c3_limb + LIVE_APPROACH_S / 3600.0, "C3")]

        for start, end, name in windows:
            if start <= hours <= end:
                self.view.set_countdown(None)
                self.view.set_live_hours(hours)
                self.view.contact = name
                edge = end if name == "C2" else start
                self.time_label.setText(f"{name} {(hours - edge) * 3600:+.1f} s")
                return

        # Otherwise count down to whichever set of beads is still to come.
        for start, _end, name in windows:
            away = (start - hours) * 3600.0
            if away > 0:
                minutes, seconds = divmod(int(away), 60)
                self.view.set_countdown(f"{name} beads in {minutes:d}:{seconds:02d}")
                self.time_label.setText(f"{name} beads in {minutes:d}:{seconds:02d}")
                self.view.set_live_hours(None)
                return

        self.view.set_countdown("eclipse over")
        self.time_label.setText("eclipse over")
        self.view.set_live_hours(None)

    def _on_contact(self, contact):
        self.view.set_contact(contact)
        self.slider.setValue(0)
        self._on_slider(0)

    def _on_slider(self, value):
        if self.solution is None:
            return
        offset = value / SLIDER_STEPS * SLIDER_RANGE_S
        self.view.set_offset(offset)
        moment = self.view.moment_hours()
        self.time_label.setText(
            f"{self.solution.to_utc(moment).strftime('%H:%M:%S.%f')[:-4]}  ({offset:+.2f} s)")
