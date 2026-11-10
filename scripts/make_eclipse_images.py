#!/usr/bin/env python3
"""Make the eclipse images of the simulated camera from a sequence of eclipse frames.

In simulation mode, with the simulated mount connected, the live view of the
virtual camera shows the sun where the mount points (sun_simulator).  These
images make that sun the real one, in the phase of the simulated time: a crop
around the sun of frames of the eclipse, at about every 90 s of the partial
phases, every 10 s in the three minutes before C2 and after C3, and a few of the
totality (the full corona).

    python scripts/make_eclipse_images.py tests/data/sun

The frames (PNG or JPEG, about 1000 px wide, the sun about 60 px in radius) must
carry their capture time (EXIF or XMP CreateDate).  The crops and eclipse.json
are written to src/solareclipseworkbench/img/eclipse.
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from solareclipseworkbench.sun_finder import find_sun  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "src" / "solareclipseworkbench" / "img" / "eclipse"

#: Half the size of a crop: room for the inner corona around a sun of 60 px
HALF = 100


def capture_time(image: Image.Image) -> datetime.datetime:
    xmp = image.info.get("XML:com.adobe.xmp", "")
    match = re.search(r'(?:xmp|photoshop):(?:CreateDate|DateCreated)="([^"]+)"', xmp)
    if match:
        return datetime.datetime.fromisoformat(match.group(1))
    exif = image.getexif().get_ifd(0x8769).get(0x9003) or image.getexif().get(0x0132)
    if exif:
        return datetime.datetime.strptime(exif, "%Y:%m:%d %H:%M:%S")
    raise ValueError("no capture time")


def bright_centre(frame: np.ndarray) -> tuple:
    """The centre of the bright pixels: for the corona, which is round enough around the moon."""
    grey = frame.max(axis=2).astype(float)
    weight = np.clip(grey - np.percentile(grey, 50) - 20, 0, None)
    ys, xs = np.mgrid[0:grey.shape[0], 0:grey.shape[1]]
    return float((xs * weight).sum() / weight.sum()), float((ys * weight).sum() / weight.sum())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("frames", type=Path, help="folder with the eclipse frames")
    parser.add_argument("--c2", default="2026-08-12T20:29:22.5+02:00", help="time of C2 in the frames")
    parser.add_argument("--c3", default="2026-08-12T20:31:10.5+02:00", help="time of C3 in the frames")
    parser.add_argument("--radius", type=float, default=60.0, help="radius of the sun in the frames, in pixels")
    parser.add_argument("--totality", default="344,350,358,380",
                        help="numbers of totality frames to keep: only a full corona, whose bright pixels are "
                             "centred on the moon (beads and the diamond ring would pull the centre off)")
    args = parser.parse_args()

    c2, c3 = datetime.datetime.fromisoformat(args.c2), datetime.datetime.fromisoformat(args.c3)
    totality = {int(n) for n in args.totality.split(",") if n}
    files = sorted(args.frames.glob("*.*"), key=lambda p: int(re.findall(r"(\d+)", p.stem)[-1]))

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.jpg"):
        old.unlink()
    entries, last_kept = [], None
    for path in files:
        number = int(re.findall(r"(\d+)", path.stem)[-1])
        image = Image.open(path)
        when = capture_time(image)
        from_c2, from_c3 = (when - c2).total_seconds(), (when - c3).total_seconds()
        near = min(abs(from_c2), abs(from_c3)) <= 180
        if number not in totality:
            if last_kept is not None and (when - last_kept).total_seconds() < (10 if near else 90):
                continue
            if from_c2 > 0 > from_c3:
                continue                            # totality: only the frames asked for
        frame = np.asarray(image.convert("RGB"))
        if number in totality:
            x, y = bright_centre(frame)
            phase = "totality" if from_c2 > 0 and from_c3 < 0 else ("C2" if abs(from_c2) < abs(from_c3) else "C3")
        else:
            fix = find_sun(frame, radius_hint=args.radius)
            if fix is None:
                continue
            x, y = fix.x, fix.y
            phase = "partial"
        left, top = int(round(x)) - HALF, int(round(y)) - HALF
        if left < 0 or top < 0 or left + 2 * HALF > frame.shape[1] or top + 2 * HALF > frame.shape[0]:
            continue                                # the sun too close to the edge of the frame
        name = f"{number:03d}.jpg"
        Image.fromarray(frame[top:top + 2 * HALF, left:left + 2 * HALF]).save(OUT / name, quality=88)
        entries.append({"file": name, "from_c2": round(from_c2, 1), "from_c3": round(from_c3, 1), "phase": phase,
                        "x": round(x - left, 2), "y": round(y - top, 2)})
        last_kept = when
        print(f"{name}  C2{from_c2:+8.1f} s  C3{from_c3:+8.1f} s  {phase}")

    manifest = {"source": "Total solar eclipse of 2026-08-12 in Spain, Canon EOS R, by Wim De Meester",
                "radius": args.radius, "frames": entries}
    (OUT / "eclipse.json").write_text(json.dumps(manifest, indent=1))
    size = sum(p.stat().st_size for p in OUT.glob("*.jpg"))
    print(f"{len(entries)} images, {size / 1024:.0f} KB, in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
