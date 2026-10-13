"""Check a lunar limb blob against the DEM it was built from.

Every value in the blob should reproduce a direct bilinear sample of the source
DEM at the same band coordinates, to within the radial quantisation.  Anything
larger means the resampling geometry or the tile packing is wrong.

Usage:
    python tools/verify_limb_blob.py LDEM_128.IMG lunar_limb_band_v1.bin
"""

import argparse
import sys

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from build_limb_blob import band_to_selenographic, sample_dem, _open_dem  # noqa: E402
from solareclipseworkbench.lunar_limb import LimbBand  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dem")
    parser.add_argument("blob")
    parser.add_argument("--samples", type=int, default=20000)
    options = parser.parse_args()

    dem = _open_dem(options.dem)
    band = LimbBand(options.blob)
    print(f"{options.blob}: {band.n_phi} x {band.n_psi} cells, "
          f"psi limit {band.psi_limit_deg:.3f} deg, quant {band.quant_m} m")

    rng = np.random.default_rng(20260812)

    # Exact cell centres: these must match the DEM sample to within quantisation.
    j = rng.integers(0, band.n_phi, options.samples)
    k = rng.integers(0, band.n_psi, options.samples)
    phi = (j + 0.5) * (360.0 / band.n_phi)
    psi = (k + 0.5 - band.n_psi / 2.0) * band.deg_per_cell

    lat, lon = band_to_selenographic(phi, psi)
    expected = sample_dem(dem, lat, lon)
    got = band.cell_radius_m(j, k)
    error = got - expected

    print(f"cell centres: max |error| {np.abs(error).max():.3f} m, "
          f"rms {np.sqrt((error ** 2).mean()):.3f} m "
          f"(quantisation allows {band.quant_m / 2:.1f} m)")

    # The mean limb ring, as a physical sanity check.
    ring_phi = np.arange(0.0, 360.0, 0.25)
    ring = band.radius_m(ring_phi, np.zeros_like(ring_phi))
    print(f"psi=0 ring: mean {ring.mean() / 1000:.3f} km, "
          f"min {ring.min() / 1000:.3f} km, max {ring.max() / 1000:.3f} km")

    # Interpolation between cells must stay inside the neighbouring cell values.
    phi_i = rng.uniform(0.0, 360.0, 2000)
    psi_i = rng.uniform(-band.psi_limit_deg, band.psi_limit_deg, 2000)
    interpolated = band.radius_m(phi_i, psi_i)
    direct = sample_dem(dem, *band_to_selenographic(phi_i, psi_i))
    residual = interpolated - direct
    print(f"interpolated: max |error| {np.abs(residual).max():.3f} m, "
          f"rms {np.sqrt((residual ** 2).mean()):.3f} m")

    ok = np.abs(error).max() <= band.quant_m / 2 + 1e-6
    print("PASS" if ok else "FAIL: cell centres exceed quantisation")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
