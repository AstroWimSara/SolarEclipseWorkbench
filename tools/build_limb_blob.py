"""Build the lunar marginal-zone blob used for limb-corrected contact times.

Only a narrow band of the lunar surface can ever appear on the limb: optical
libration reaches about 7.9 deg in longitude and 6.9 deg in latitude (about
10.4 deg combined), and topocentric parallax adds up to another 1.0 deg.  So
every point that can ever be seen in profile lies within roughly 11.5 deg of
the mean limb great circle -- about 6% of the Moon.  This script resamples that
band out of the LOLA LDEM into a limb-natural coordinate system and packs it.

Band coordinates, with the mean sub-Earth direction as (1, 0, 0):

    x = sin(psi)                psi = angular distance from the mean limb plane
    y = cos(psi) * cos(phi)     phi = angle around the limb, 0 at the east point
    z = cos(psi) * sin(phi)           and +90 deg at the north pole

The grid is nearly metrically uniform: spacing along phi scales as cos(psi), so
it varies by at most 2% across the band, and the frame's own poles sit at the
sub-Earth point and its antipode -- far outside the band, so there is no polar
singularity to handle.

Source: LOLA LDEM_128 (LRO-L-LOLA-4-GDR-V1.0), 128 pixels/degree, 236.9 m/pixel,
global, radii in the DE421 mean Earth/polar axis frame relative to 1737.4 km.

Usage:
    python tools/build_limb_blob.py LDEM_128.IMG lunar_limb_band_v1.bin
"""

import argparse
import concurrent.futures
import json
import lzma
import struct
import sys
import time

import numpy as np

MAGIC = b"SEWLIMB\x01"

# LDEM_128 geometry, from the PDS label.
DEM_LINES = 23040
DEM_SAMPLES = 46080
DEM_RES = 128.0            # pixels per degree
DEM_SCALE_M = 0.5          # metres per DN
DEM_OFFSET_M = 1737400.0   # reference sphere radius

# Output grid.  Same angular resolution as the source, so nothing is
# downsampled away: peaks and valleys both survive at their native size.
N_PHI = 46080              # 1/128 deg around the limb, 237 m
N_PSI = 3072               # 1/128 deg across it: psi in [-12 deg, +12 deg]
TILE_PHI = 512
TILE_PSI = 256

# Radial quantisation.  4 m is 0.005 s of contact time at the ~0.8 km/s closing
# speed of the limbs -- far below the LOLA vertical accuracy, and it buys a
# large amount of compression.
QUANT_M = 4

LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]

_dem = None


def _open_dem(path):
    return np.memmap(path, dtype="<i2", mode="r", shape=(DEM_LINES, DEM_SAMPLES))


def _init_worker(path):
    global _dem
    _dem = _open_dem(path)


def sample_dem(dem, lat_deg, lon_deg):
    """Bilinearly sample the DEM, returning radius in metres.

    The DEM is pixel-registered: cell (i, j) is centred on
    lat = 90 - (i + 0.5)/128, lon = (j + 0.5)/128 east.  That is the only
    reading under which the 23040 rows tile [-90, +90] exactly; the label's
    LINE/SAMPLE_PROJECTION_OFFSET values are off by a pixel and would run past
    the pole.
    """
    fi = (90.0 - lat_deg) * DEM_RES - 0.5
    fj = (lon_deg % 360.0) * DEM_RES - 0.5

    i0 = np.floor(fi).astype(np.int64)
    j0 = np.floor(fj).astype(np.int64)
    ti = (fi - i0).astype(np.float32)
    tj = (fj - j0).astype(np.float32)

    i0 = np.clip(i0, 0, DEM_LINES - 2)
    i1 = i0 + 1
    j0 %= DEM_SAMPLES
    j1 = (j0 + 1) % DEM_SAMPLES

    v00 = dem[i0, j0].astype(np.float32)
    v01 = dem[i0, j1].astype(np.float32)
    v10 = dem[i1, j0].astype(np.float32)
    v11 = dem[i1, j1].astype(np.float32)

    top = v00 + (v01 - v00) * tj
    bot = v10 + (v11 - v10) * tj
    dn = top + (bot - top) * ti
    return dn * DEM_SCALE_M + DEM_OFFSET_M


def band_to_selenographic(phi_deg, psi_deg):
    """Map band coordinates to selenographic latitude and east longitude."""
    phi = np.radians(phi_deg)
    psi = np.radians(psi_deg)
    cos_psi = np.cos(psi)

    x = np.sin(psi)
    y = cos_psi * np.cos(phi)
    z = cos_psi * np.sin(phi)

    lat = np.degrees(np.arcsin(np.clip(z, -1.0, 1.0)))
    lon = np.degrees(np.arctan2(y, x))
    return lat, lon


def build_tile(args):
    """Resample and compress one tile.  Returns (index, payload, peak-to-peak)."""
    tile_index, j0, k0 = args

    j = np.arange(j0, j0 + TILE_PHI, dtype=np.float64)
    k = np.arange(k0, k0 + TILE_PSI, dtype=np.float64)
    phi = (j + 0.5) * (360.0 / N_PHI)
    psi = (k + 0.5 - N_PSI / 2.0) / DEM_RES

    lat, lon = band_to_selenographic(phi[None, :], psi[:, None])
    radius_m = sample_dem(_dem, lat, lon)

    quantised = np.round((radius_m - DEM_OFFSET_M) / QUANT_M).astype(np.int32)
    if quantised.min() < -32768 or quantised.max() > 32767:
        raise ValueError(f"tile {tile_index}: quantised radius overflows int16")

    values = quantised.astype("<i2")
    # Prepend zero, not the first column: the leading entry has to carry the
    # row's absolute value so that a plain cumsum reconstructs it.
    delta = np.diff(values.astype(np.int32), axis=1, prepend=0).astype("<i2")
    payload = lzma.compress(delta.tobytes(), format=lzma.FORMAT_RAW,
                            filters=LZMA_FILTERS)
    return tile_index, payload, int(quantised.min()), int(quantised.max())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dem", help="path to LDEM_128.IMG")
    parser.add_argument("out", help="path to write the blob to")
    parser.add_argument("--jobs", type=int, default=0,
                        help="worker processes (default: one per core)")
    options = parser.parse_args()

    n_tile_phi = N_PHI // TILE_PHI
    n_tile_psi = N_PSI // TILE_PSI
    n_tiles = n_tile_phi * n_tile_psi

    work = []
    for tj in range(n_tile_phi):
        for tk in range(n_tile_psi):
            work.append((tj * n_tile_psi + tk, tj * TILE_PHI, tk * TILE_PSI))

    print(f"resampling {N_PHI} x {N_PSI} cells into {n_tiles} tiles "
          f"({N_PHI * N_PSI * 2 / 1e6:.0f} MB uncompressed)")

    payloads = [None] * n_tiles
    lo, hi = 32767, -32768
    started = time.monotonic()
    done = 0

    with concurrent.futures.ProcessPoolExecutor(
            max_workers=options.jobs or None,
            initializer=_init_worker, initargs=(options.dem,)) as pool:
        for tile_index, payload, tile_lo, tile_hi in pool.map(build_tile, work, chunksize=4):
            payloads[tile_index] = payload
            lo = min(lo, tile_lo)
            hi = max(hi, tile_hi)
            done += 1
            if done % 60 == 0 or done == n_tiles:
                elapsed = time.monotonic() - started
                packed = sum(len(p) for p in payloads if p is not None)
                print(f"  {done}/{n_tiles} tiles  {packed / 1e6:6.1f} MB  "
                      f"{elapsed:5.0f}s", flush=True)

    header = {
        "format": "sew-lunar-limb-band",
        "version": 1,
        "source": "LOLA LDEM_128 (LRO-L-LOLA-4-GDR-V1.0), DE421 mean Earth/polar axis frame",
        "frame": "selenographic ME; band x=sin(psi), y=cos(psi)cos(phi), z=cos(psi)sin(phi)",
        "n_phi": N_PHI,
        "n_psi": N_PSI,
        "deg_per_cell": 1.0 / DEM_RES,
        "phi_deg": "phi = (j + 0.5) * 360 / n_phi, 0 at the east point, +90 at the north pole",
        "psi_deg": "psi = (k + 0.5 - n_psi/2) / 128, positive towards the sub-Earth point",
        "tile_phi": TILE_PHI,
        "tile_psi": TILE_PSI,
        "n_tile_phi": n_tile_phi,
        "n_tile_psi": n_tile_psi,
        "tile_order": "tile_index = tile_j * n_tile_psi + tile_k",
        "quant_m": QUANT_M,
        "ref_radius_m": DEM_OFFSET_M,
        "value": "radius_m = ref_radius_m + int16 * quant_m",
        "codec": "int16 delta along phi, then raw LZMA2 preset 6",
        "radius_min_m": DEM_OFFSET_M + lo * QUANT_M,
        "radius_max_m": DEM_OFFSET_M + hi * QUANT_M,
    }
    header_bytes = json.dumps(header, indent=1).encode("utf-8")

    index = bytearray()
    offset = 0
    for payload in payloads:
        index += struct.pack("<QI", offset, len(payload))
        offset += len(payload)

    with open(options.out, "wb") as blob:
        blob.write(MAGIC)
        blob.write(struct.pack("<I", len(header_bytes)))
        blob.write(header_bytes)
        blob.write(index)
        for payload in payloads:
            blob.write(payload)

    total = len(MAGIC) + 4 + len(header_bytes) + len(index) + offset
    print(f"wrote {options.out}: {total / 1e6:.1f} MB "
          f"({N_PHI * N_PSI * 2 / offset:.2f}x on the tile data)")
    print(f"limb radius range: {header['radius_min_m'] / 1000:.3f} .. "
          f"{header['radius_max_m'] / 1000:.3f} km")
    return 0


if __name__ == "__main__":
    sys.exit(main())
