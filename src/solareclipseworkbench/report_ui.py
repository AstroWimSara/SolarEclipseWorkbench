"""Windows for the script timeline (before a run) and the run report (after it).

Both are opened from the toolbar of the main window: "Timeline" draws a script
per camera against the reference moments (see script_timeline), "Run report"
reads a log file back and shows what became of every command (see run_report).
"""

import logging
from pathlib import Path
from typing import Callable, Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                             QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from solareclipseworkbench import run_report
from solareclipseworkbench.script_timeline import build_timeline, command_at, describe, draw_timeline, format_timeline


class TimelineWindow(QWidget):
    """A script per camera, with the contacts: which commands start late or are dropped, and why.

    The window is given a function that returns the reference moments and the
    cameras, so it always draws against the location and date currently set.
    """

    def __init__(self, context: Callable[[], tuple], parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Script timeline")
        self.resize(1100, 520)
        self._context = context
        self.filename: Optional[str] = None
        self.timeline = None
        self._artists = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        controls = QHBoxLayout()
        self.script_button = QPushButton("Script...")
        self.script_button.setToolTip("Choose the script to draw")
        self.script_button.clicked.connect(self.choose_script)
        controls.addWidget(self.script_button)
        self.range_box = QComboBox()
        self.range_box.addItems(["Totality", "Whole script"])
        self.range_box.setToolTip("Show the commands around totality, or all of them")
        self.range_box.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.range_box)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Read the script again, e.g. after editing it")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        self.text_button = QPushButton("Save as text...")
        self.text_button.setToolTip("Save the timeline of every camera as a text file")
        self.text_button.clicked.connect(self.save_text)
        controls.addWidget(self.text_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary = QLabel("Choose a script")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.figure = Figure(figsize=(10, 4))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas, 1)

        self.hover = QLabel(" ")
        self.hover.setWordWrap(True)
        self.hover.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.hover)

    def set_script(self, filename: Optional[str]):
        """Draw this script (None: keep the current one)."""
        if filename:
            self.filename = filename
        self.refresh()

    def choose_script(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Script to draw", str(Path(self.filename).parent)
                                                  if self.filename else "", "Text Files (*.txt);;All Files (*)")
        if filename:
            self.set_script(filename)

    def refresh(self):
        if not self.filename:
            self.summary.setText("Choose a script")
            return
        reference_moments, cameras = self._context()
        if not reference_moments:
            self.summary.setText("Set the location and the date first: the timeline is drawn against the "
                                 "reference moments.")
            return
        try:
            self.timeline = build_timeline(self.filename, reference_moments, cameras)
        except Exception as e:
            logging.exception("Could not lay out %s", self.filename)
            self.summary.setText(f"Could not read {self.filename}: {e}")
            return
        self.setWindowTitle(f"Script timeline: {Path(self.filename).name}")
        self.redraw()

    def redraw(self):
        if self.timeline is None:
            return
        timeline = self.timeline
        self._artists = draw_timeline(self.figure, timeline, totality_only=self.range_box.currentIndex() == 0)
        self.canvas.draw_idle()
        cameras = len(timeline.cameras)
        parts = [f"{len(timeline.camera_commands())} camera command(s) on {cameras} camera(s)"]
        if timeline.dropped:
            parts.append(f"<b style='color:#d62728'>{len(timeline.dropped)} will probably be dropped</b>")
        if timeline.late:
            parts.append(f"<b style='color:#e69f00'>{len(timeline.late)} start late</b>")
        if not timeline.dropped and not timeline.late:
            parts.append("no command has to wait for its camera")
        for name, count in timeline.unknown_moments.items():
            parts.append(f"<b style='color:#d62728'>{count} line(s) against {name}, which does not exist here</b>")
        self.summary.setText("; ".join(parts) + ".  Hover over a bar for its command.")

    def _on_hover(self, event):
        if self.timeline is None or event.inaxes is None:
            return
        command = command_at(self._artists, event)
        self.hover.setText(describe(self.timeline, command) if command is not None else " ")

    def save_text(self):
        if self.timeline is None:
            return
        default = str(Path(self.filename).with_suffix(".timeline.txt")) if self.filename else ""
        filename, _ = QFileDialog.getSaveFileName(self, "Save timeline", default, "Text Files (*.txt)")
        if filename:
            _write_text(self, filename, format_timeline(self.timeline))


# Run report

STATUS_COLOURS = {"dropped: camera busy": "#d62728", "missed by the scheduler": "#d62728", "failed": "#d62728",
                  "no shutter release": "#d62728", "late": "#e69f00", "no record": "#7f7f7f",
                  "not reached": "#7f7f7f"}

COLUMNS = ("Planned UTC", "Reference", "Camera", "Command", "Status", "Delay s", "Busy s", "Est. s", "Description")
NUMERIC_COLUMNS = (5, 6, 7)


class _NumericItem(QTableWidgetItem):
    """Sorts by number rather than by text; "-" (no value) sorts first."""

    def _value(self):
        try:
            return float(self.text())
        except ValueError:
            return float("-inf")

    def __lt__(self, other):
        return self._value() < other._value() if isinstance(other, _NumericItem) else super().__lt__(other)


class RunReportWindow(QWidget):
    """What became of every command of a run, from its log file."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Run report")
        self.resize(1150, 650)
        self.log_path: Optional[Path] = None
        self.runs = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Log:"))
        self.log_box = QComboBox()
        self.log_box.setMinimumWidth(320)
        self.log_box.activated.connect(lambda _: self.open_log(self.log_box.currentData()))
        controls.addWidget(self.log_box)
        self.open_button = QPushButton("Open...")
        self.open_button.setToolTip("Open another log file")
        self.open_button.clicked.connect(self.choose_log)
        controls.addWidget(self.open_button)
        controls.addWidget(QLabel("Run:"))
        self.run_box = QComboBox()
        self.run_box.setToolTip("Each time a script is loaded starts a run")
        self.run_box.currentIndexChanged.connect(self.show_run)
        controls.addWidget(self.run_box, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Read the log again, e.g. while a run is going on")
        self.refresh_button.clicked.connect(lambda: self.open_log(self.log_path, keep_run=True))
        controls.addWidget(self.refresh_button)
        self.text_button = QPushButton("Save as text...")
        self.text_button.clicked.connect(self.save_text)
        controls.addWidget(self.text_button)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.summary.setFont(font)
        splitter.addWidget(self.summary)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.table)
        splitter.setSizes([260, 390])
        layout.addWidget(splitter, 1)

        self.fill_logs()

    def fill_logs(self, current: Optional[Path] = None):
        """List the log files in which a script was loaded, newest first, and open the newest (or current)."""
        logs = run_report.run_logs()
        if current is not None and current not in logs:
            logs.insert(0, current)
        self.log_box.clear()
        for path in logs:
            self.log_box.addItem(path.name, path)
        if not logs:
            self.summary.setPlainText(f"No log with a loaded script in {run_report.LOG_DIR}.  Load a script (a "
                                      f"simulation is fine) and run it, then come back here.")
            return
        index = logs.index(current) if current is not None else 0
        self.log_box.setCurrentIndex(index)
        self.open_log(logs[index])

    def choose_log(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Log file", str(run_report.LOG_DIR),
                                                  "Log Files (*.log);;All Files (*)")
        if filename:
            self.fill_logs(Path(filename))

    def open_log(self, path: Optional[Path], keep_run: bool = False):
        if path is None:
            return
        previous = self.run_box.currentIndex()
        try:
            self.runs = run_report.read_log(path)
        except OSError as e:
            QMessageBox.warning(self, "Run report", f"Could not read {path}:\n{e}")
            return
        self.log_path = Path(path)
        self.run_box.blockSignals(True)
        self.run_box.clear()
        for run in self.runs:
            planned = sum(1 for c in run.commands if c.planned is not None)
            self.run_box.addItem(f"{run.started.strftime('%Y-%m-%d %H:%M:%S')} UTC — {Path(run.script).name} "
                                 f"({planned} commands)")
        self.run_box.blockSignals(False)
        if not self.runs:
            self.summary.setPlainText(f"No script was loaded in {path}.")
            self.table.setRowCount(0)
            return
        self.run_box.setCurrentIndex(previous if keep_run and 0 <= previous < len(self.runs) else len(self.runs) - 1)
        self.show_run()

    @property
    def run(self):
        index = self.run_box.currentIndex()
        return self.runs[index] if 0 <= index < len(self.runs) else None

    def show_run(self):
        run = self.run
        if run is None:
            return
        text = run_report.format_report(run, self.log_path)
        # The table below lists every command
        self.summary.setPlainText(text.split("\nAll commands\n")[0].rstrip() + "\n\n" + _problems_text(run))

        commands = sorted(run.commands, key=lambda c: (c.planned or c.released_at or run.started))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(commands))
        for row, command in enumerate(commands):
            status = run.status_of(command)
            values = (run_report._hms(command.planned), command.reference, command.camera or "-", command.func_name,
                      status, run_report._seconds(command.delay_s, True), run_report._seconds(command.busy_s),
                      run_report._seconds(command.estimated_busy_s), command.description)
            for column, value in enumerate(values):
                item = _NumericItem(value) if column in NUMERIC_COLUMNS else QTableWidgetItem(value)
                if column == 4 and status in STATUS_COLOURS:
                    item.setForeground(QColor(STATUS_COLOURS[status]))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def save_text(self):
        run = self.run
        if run is None:
            return
        default = str(self.log_path.with_suffix(".report.txt")) if self.log_path else ""
        filename, _ = QFileDialog.getSaveFileName(self, "Save run report", default, "Text Files (*.txt)")
        if filename:
            _write_text(self, filename, run_report.format_report(run, self.log_path))


def _problems_text(run) -> str:
    if not run.problems:
        return "No warnings or errors were logged during this run."
    shown = run.problems[:50]
    more = f"\n... and {len(run.problems) - 50} more in the log file" if len(run.problems) > 50 else ""
    return f"Warnings and errors ({len(run.problems)})\n" + "\n".join(shown) + more


def _write_text(parent, filename: str, text: str):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        QMessageBox.warning(parent, "Save", f"Could not write {filename}:\n{e}")
