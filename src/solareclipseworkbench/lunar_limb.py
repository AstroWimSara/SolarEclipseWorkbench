"""Reader for the lunar marginal-zone blob.

The blob holds the radius of every point on the Moon that can ever appear on
the limb -- a band of about +/-12 degrees around the mean limb great circle --
resampled into limb-natural coordinates.  See tools/build_limb_blob.py for how
it is built and what phi and psi mean.

Tiles are decompressed on demand and cached, because a single limb profile
touches only a thin sinusoid through the band, not the whole dataset.
"""

import json
import lzma
import struct
from collections import OrderedDict
from pathlib import Path

import numpy as np

MAGIC = b"SEWLIMB\x01"
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]

# A profile crosses every tile column but only one or two tile rows, so a cache
# of a few hundred tiles covers a whole evaluation with room to spare.
MAX_CACHED_TILES = 256


class LimbBand:
    """Random access to the lunar limb-band radii."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with open(self.path, "rb") as blob:
            if blob.read(len(MAGIC)) != MAGIC:
                raise ValueError(f"{self.path} is not a lunar limb band blob")
            header_length, = struct.unpack("<I", blob.read(4))
            self.header = json.loads(blob.read(header_length))

            self.n_phi = self.header["n_phi"]
            self.n_psi = self.header["n_psi"]
            self.tile_phi = self.header["tile_phi"]
            self.tile_psi = self.header["tile_psi"]
            self.n_tile_phi = self.header["n_tile_phi"]
            self.n_tile_psi = self.header["n_tile_psi"]
            self.quant_m = self.header["quant_m"]
            self.ref_radius_m = self.header["ref_radius_m"]
            self.deg_per_cell = self.header["deg_per_cell"]

            n_tiles = self.n_tile_phi * self.n_tile_psi
            index = blob.read(n_tiles * 12)
            self._index = [struct.unpack_from("<QI", index, i * 12) for i in range(n_tiles)]
            self._data_start = blob.tell()

        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()

    def _tile(self, tile_j: int, tile_k: int) -> np.ndarray:
        tile_index = tile_j * self.n_tile_psi + tile_k
        cached = self._cache.get(tile_index)
        if cached is not None:
            self._cache.move_to_end(tile_index)
            return cached

        offset, length = self._index[tile_index]
        with open(self.path, "rb") as blob:
            blob.seek(self._data_start + offset)
            payload = blob.read(length)

        delta = np.frombuffer(
            lzma.decompress(payload, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS),
            dtype="<i2",
        ).reshape(self.tile_psi, self.tile_phi)
        tile = np.cumsum(delta.astype(np.int32), axis=1).astype(np.int32)

        self._cache[tile_index] = tile
        if len(self._cache) > MAX_CACHED_TILES:
            self._cache.popitem(last=False)
        return tile

    def cell_radius_m(self, j, k):
        """Radius in metres at integer band cells (j along phi, k across psi)."""
        j = np.asarray(j, dtype=np.int64) % self.n_phi
        k = np.clip(np.asarray(k, dtype=np.int64), 0, self.n_psi - 1)

        out = np.empty(np.broadcast(j, k).shape, dtype=np.float64)
        j, k = np.broadcast_arrays(j, k)
        tile_j, tile_k = j // self.tile_phi, k // self.tile_psi

        for tj, tk in {(int(a), int(b)) for a, b in zip(tile_j.ravel(), tile_k.ravel())}:
            here = (tile_j == tj) & (tile_k == tk)
            tile = self._tile(tj, tk)
            out[here] = tile[k[here] - tk * self.tile_psi, j[here] - tj * self.tile_phi]

        return self.ref_radius_m + out * self.quant_m

    def radius_m(self, phi_deg, psi_deg):
        """Bilinearly interpolated radius in metres at band coordinates."""
        phi_deg = np.asarray(phi_deg, dtype=np.float64)
        psi_deg = np.asarray(psi_deg, dtype=np.float64)

        fj = (phi_deg % 360.0) / (360.0 / self.n_phi) - 0.5
        fk = psi_deg / self.deg_per_cell + self.n_psi / 2.0 - 0.5

        j0 = np.floor(fj).astype(np.int64)
        k0 = np.floor(fk).astype(np.int64)
        tj = fj - j0
        tk = fk - k0

        v00 = self.cell_radius_m(j0, k0)
        v01 = self.cell_radius_m(j0 + 1, k0)
        v10 = self.cell_radius_m(j0, k0 + 1)
        v11 = self.cell_radius_m(j0 + 1, k0 + 1)

        top = v00 + (v01 - v00) * tj
        bottom = v10 + (v11 - v10) * tj
        return top + (bottom - top) * tk

    @property
    def psi_limit_deg(self) -> float:
        """Largest libration plus parallax the blob can answer for."""
        return (self.n_psi / 2.0 - 1.0) * self.deg_per_cell
