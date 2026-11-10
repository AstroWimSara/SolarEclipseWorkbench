"""Sorting the images of a run by the script line that took them (image_sorter)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from solareclipseworkbench import image_sorter as sorter
from solareclipseworkbench import run_report

C1 = datetime(2026, 8, 12, 17, 31, 0, tzinfo=timezone.utc)
C2 = datetime(2026, 8, 12, 18, 29, 22, tzinfo=timezone.utc)
C3 = datetime(2026, 8, 12, 18, 31, 10, tzinfo=timezone.utc)
C4 = datetime(2026, 8, 12, 19, 26, 0, tzinfo=timezone.utc)
CAMERA = "Canon EOS R"


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _line(moment: datetime, message: str, thread: str = "MainThread") -> str:
    return f"{_stamp(moment)} INFO     [{thread}] root: {message}"


def _ref(name: str, moment: datetime, at: datetime) -> str:
    seconds = (at - moment).total_seconds()
    sign = "+" if seconds >= 0 else "-"
    s = abs(seconds)
    return f"{name}{sign}{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{s % 60:04.1f}"


class _Log:
    """A log of a run, built command by command; each command released the shutter 0.1 s late."""

    def __init__(self, shift: timedelta = timedelta(0)):
        self.shift = shift          # simulation: planned = eclipse time + shift
        start = C1 - timedelta(minutes=5) + shift
        self.lines = [_line(start, "Starting observation with script /tmp/eclipse.txt")]
        for name, moment in (("C1", C1), ("C2", C2), ("C3", C3), ("C4", C4)):
            self.lines.append(_line(start, f"Reference moment {name}: {moment.strftime('%Y-%m-%d %H:%M:%S.%f')[:-5]} UTC"))
        self.lines.append(_line(start, f"Cameras: {CAMERA}"))
        self.events = []

    def add(self, func: str, contact: str, at: datetime, busy: float, description: str,
            camera: str = CAMERA, dropped: bool = False):
        moment = {"C1": C1, "C2": C2, "C3": C3, "C4": C4}[contact]
        planned = at + self.shift
        when = planned.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.lines.append(_line(C1 - timedelta(minutes=5) + self.shift,
                                f"Planned: {func} | {camera} | {when} UTC | {_ref(contact, moment, at)} | "
                                f"busy {busy:.1f} s | {description}"))
        tod = planned.strftime("%H:%M:%S.%f")[:-3]
        if dropped:
            self.events.append((planned, _line(planned, f"{camera}: {func} (scheduled {tod} UTC) dropped — camera "
                                                        f"was still busy", "ThreadPoolExecutor-0_0")))
            return planned
        released = planned + timedelta(seconds=0.1)
        self.events.append((released, _line(released, f"{camera}: {func} released the shutter at "
                                                      f"{released.strftime('%H:%M:%S.%f')[:-3]} UTC: 0.100 s after "
                                                      f"its scheduled time (0.100 s after the command started)",
                                            "ThreadPoolExecutor-0_0")))
        done = planned + timedelta(seconds=busy)
        self.events.append((done, _line(done, f"{camera}: {func} (scheduled {tod} UTC) finished: the camera was "
                                              f"busy {busy:.3f} s", "ThreadPoolExecutor-0_0")))
        return released

    def run(self) -> run_report.Run:
        lines = self.lines + [line for _, line in sorted(self.events, key=lambda e: e[0])]
        return run_report.parse_log(lines)[-1]


def _image(name: str, taken: datetime, model: str = CAMERA, subsec: bool = True) -> sorter.ImageInfo:
    taken = taken.replace(tzinfo=None)
    if not subsec:
        taken = taken.replace(microsecond=0)
    return sorter.ImageInfo(Path(name), taken, subsec, "Canon", model, "")


def _eclipse(log: _Log):
    """A script: partial phase every 10 min, a 5-frame bracket at C2-4 s, a 7-frame HDR in totality,
    a burst after C3, one dropped picture.  Returns the shutter releases per label."""
    shots = {}
    for i in range(5):
        at = C1 + timedelta(minutes=10 * i + 2)
        shots.setdefault("partial", []).append([log.add("take_picture", "C1", at, 1.0, "partial")])
    released = log.add("take_bracket", "C2", C2 - timedelta(seconds=4), 3.0, "diamond ring")
    shots["diamond ring"] = [[released + timedelta(seconds=0.4 * k) for k in range(5)]]
    released = log.add("take_hdr", "C2", C2 + timedelta(seconds=30), 6.0, "corona HDR")
    shots["corona HDR"] = [[released + timedelta(seconds=0.8 * k) for k in range(7)]]
    released = log.add("take_burst", "C3", C3 + timedelta(seconds=1), 2.0, "beads C3")
    shots["beads C3"] = [[released + timedelta(seconds=0.2 * k) for k in range(10)]]
    log.add("take_picture", "C3", C3 + timedelta(seconds=20), 1.0, "dropped one", dropped=True)
    return shots


def _images_for(shots, clock_offset: timedelta, subsec: bool = True):
    images = []
    n = 1000
    for label, commands in shots.items():
        for releases in commands:
            for moment in releases:
                images.append(_image(f"IMG_{n}.CR3", moment + timedelta(seconds=0.05) + clock_offset, subsec=subsec))
                n += 1
    return images


def test_sorts_into_phase_label_and_group_folders():
    log = _Log()
    shots = _eclipse(log)
    offset = timedelta(hours=2, seconds=3.4)      # camera on local summer time, and 3.4 s fast
    images = _images_for(shots, offset)
    images.append(_image("IMG_9999.CR3", C1 - timedelta(minutes=30) + offset))   # a test shot
    plan = sorter.plan_sorting(log.run(), images)

    (_cameras, fit), = plan.fits.values()
    assert fit.offset_s == pytest.approx(offset.total_seconds(), abs=0.3)
    assert len(plan.matched) == 5 + 5 + 7 + 10
    assert [p.image.path.name for p in plan.unmatched] == ["IMG_9999.CR3"]

    folders = {}
    for p in plan.matched:
        folders.setdefault(str(p.destination.parent), []).append(p.destination.name)
    assert len(folders["1_C1-C2/partial"]) == 5
    bracket = next(f for f in folders if f.startswith("1_C1-C2/diamond ring/"))
    assert bracket.endswith("_C2-00h00m04.0s_take_bracket")
    assert sorted(folders[bracket])[0].startswith("001_")
    assert len(folders[bracket]) == 5
    hdr = next(f for f in folders if f.startswith("2_C2-C3/corona HDR/"))
    assert len(folders[hdr]) == 7
    burst = next(f for f in folders if f.startswith("3_C3-C4/beads C3/"))
    assert len(folders[burst]) == 10
    assert not plan.warnings


def test_capture_times_to_the_second():
    """Without sub-seconds every frame of a burst has the same few times; still all of them are found."""
    log = _Log()
    shots = _eclipse(log)
    offset = timedelta(seconds=-41.7)
    plan = sorter.plan_sorting(log.run(), _images_for(shots, offset, subsec=False))
    assert len(plan.matched) == 27
    assert not plan.unmatched


def test_simulation_phases_follow_the_reference_not_the_computer_clock():
    """In a simulation the commands run days after the eclipse; the phase is still the one written for."""
    log = _Log(shift=timedelta(days=-90, minutes=13, seconds=7))
    shots = _eclipse(log)
    plan = sorter.plan_sorting(log.run(), _images_for(shots, timedelta(seconds=1.5)))
    phases = {p.command.label: p.command.phase for p in plan.matched}
    assert phases == {"partial": "1_C1-C2", "diamond ring": "1_C1-C2", "corona HDR": "2_C2-C3",
                      "beads C3": "3_C3-C4"}


def test_given_clock_offset_is_used():
    log = _Log()
    shots = _eclipse(log)
    plan = sorter.plan_sorting(log.run(), _images_for(shots, timedelta(seconds=10)), clock_offset_s=10.0)
    (_cameras, fit), = plan.fits.values()
    assert fit.offset_s == 10.0
    assert len(plan.matched) == 27


def test_two_bodies_are_matched_to_their_own_camera():
    log = _Log()
    a = log.add("take_picture", "C2", C2 + timedelta(seconds=10), 1.0, "corona wide", camera=CAMERA)
    b = log.add("take_bracket", "C2", C2 + timedelta(seconds=10), 3.0, "corona tele", camera="Nikon Z 6")
    images = [_image("A.CR3", a + timedelta(seconds=5)),
              _image("B1.NEF", b - timedelta(seconds=2), model="NIKON Z 6"),
              _image("B2.NEF", b - timedelta(seconds=1), model="NIKON Z 6")]
    plan = sorter.plan_sorting(log.run(), images, clock_offset_s=None)
    where = {p.image.path.name: p for p in plan.matched}
    assert where["A.CR3"].camera == CAMERA
    assert where["B1.NEF"].camera == "Nikon Z 6"
    assert str(where["A.CR3"].destination).startswith("Canon EOS R/2_C2-C3/corona wide/")
    assert "take_bracket" in str(where["B2.NEF"].destination.parent)


def test_images_without_time_go_to_unmatched():
    log = _Log()
    _eclipse(log)
    plan = sorter.plan_sorting(log.run(), [sorter.ImageInfo(Path("x.jpg"))])
    assert plan.unmatched[0].reason == "no capture time"
    assert plan.unmatched[0].destination == Path("unmatched/x.jpg")


def test_apply_copies_and_writes_manifest(tmp_path):
    log = _Log()
    released = log.add("take_picture", "C2", C2 + timedelta(seconds=10), 1.0, "corona: wide/1")
    source = tmp_path / "card"
    source.mkdir()
    (source / "IMG_1.JPG").write_bytes(b"x")
    (source / "IMG_2.JPG").write_bytes(b"y")
    images = [sorter.ImageInfo(source / "IMG_1.JPG", released.replace(tzinfo=None), True, "Canon", CAMERA),
              sorter.ImageInfo(source / "IMG_2.JPG", (released + timedelta(minutes=9)).replace(tzinfo=None),
                               True, "Canon", CAMERA)]
    plan = sorter.plan_sorting(log.run(), images, clock_offset_s=0.0)
    out = tmp_path / "sorted"
    manifest = sorter.apply_plan(plan, out)
    copied = [p for p in out.rglob("*.JPG")]
    assert len(copied) == 2
    sorted_one = next(p for p in copied if p.name.endswith("IMG_1.JPG"))
    assert sorted_one.parent.name == "corona_ wide_1"      # no : or / in a folder name
    assert (source / "IMG_1.JPG").exists()                 # copied, not moved
    assert (out / "unmatched" / "IMG_2.JPG").exists()
    assert "C2+00:00:10.0" in manifest.read_text()


def test_reads_exif_of_a_jpeg(tmp_path):
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0110] = "Canon EOS R"
    exif.get_ifd(0x8769)[0x9003] = "2026:08:12 20:29:18"
    exif.get_ifd(0x8769)[0x9291] = "37"
    exif.get_ifd(0x8769)[0xA431] = "123456"
    path = tmp_path / "IMG_0001.JPG"
    Image.new("RGB", (8, 8)).save(path, exif=exif)
    info = sorter.read_image_info(path)
    assert info.taken == datetime(2026, 8, 12, 20, 29, 18, 370000)
    assert info.has_subseconds
    assert info.model == "Canon EOS R"
    assert info.body == "Canon EOS R #123456"


def _tiff(entries0, entries_exif) -> bytes:
    """A big-endian TIFF (as a NEF) with IFD0 and an EXIF IFD, ASCII tags only."""
    import struct

    def ifd(entries, at, extra_tags=()):
        count = len(entries) + len(extra_tags)
        data_at = at + 2 + 12 * count + 4
        head, blob = struct.pack(">H", count), b""
        for tag, kind, value in sorted(list(entries) + list(extra_tags)):
            if kind == 2:
                raw = value.encode() + b"\x00"
                if len(raw) <= 4:       # fits in the entry itself
                    head += struct.pack(">HHI", tag, 2, len(raw)) + raw.ljust(4, b"\x00")
                    continue
                head += struct.pack(">HHII", tag, 2, len(raw), data_at + len(blob))
                blob += raw
            else:
                head += struct.pack(">HHII", tag, 4, 1, value)
        return head + b"\x00\x00\x00\x00" + blob

    entries0 = [(tag, 2, value) for tag, value in entries0]
    first = ifd(entries0, 8, [(0x8769, 4, 0)])
    exif_at = 8 + len(first)
    first = ifd(entries0, 8, [(0x8769, 4, exif_at)])
    return b"MM\x00\x2a" + struct.pack(">I", 8) + first + ifd([(t, 2, v) for t, v in entries_exif], exif_at)


def test_reads_exif_of_a_tiff_based_raw(tmp_path):
    path = tmp_path / "DSC_0001.NEF"
    path.write_bytes(_tiff([(0x010F, "NIKON CORPORATION"), (0x0110, "NIKON Z 6")],
                           [(0x9003, "2026:08:12 20:29:18"), (0x9291, "5"), (0xA431, "6012345")]))
    info = sorter.read_image_info(path)
    assert info.taken == datetime(2026, 8, 12, 20, 29, 18, 500000)
    assert info.has_subseconds
    assert info.model == "NIKON Z 6"
    assert info.serial == "6012345"


def test_names():
    assert sorter.reference_name("C2-00:00:04.0") == "C2-00h00m04.0s"
    assert sorter.reference_name("max+00:01:30") == "MAX+00h01m30.0s"
    assert sorter.safe_name('a: "b"/c?') == "a_ _b_c_"
    assert sorter.parse_offset("-01:00:02.5") == -3602.5
    assert sorter.parse_offset("12.5") == 12.5


def test_cameras_for_body_finds_aliases():
    names = ["Canon EOS 80D", "Canon EOS 80D met PhotoLine 80", "NIKON Z 6"]
    body = sorter.ImageInfo(Path("x"), model="Canon EOS 80D")
    assert sorter.cameras_for_body(body, names) == names[:2]
    assert sorter.cameras_for_body(sorter.ImageInfo(Path("x"), model="Z 6"), names) == ["NIKON Z 6"]


def test_partial_eclipse_has_one_partial_phase():
    run = run_report.Run(script="x", started=C1, reference_moments={"C1": C1, "MAX": C2, "C4": C4})
    assert [name for name, _ in sorter.phase_names(run)] == ["0_before_C1", "1_C1-C4", "2_after_C4"]
