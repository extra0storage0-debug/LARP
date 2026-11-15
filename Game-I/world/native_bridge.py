"""The optional compiled maths in native/sentry_native.dll, and how Python reaches it.

If the DLL is missing, refused by Windows, or switched off with SENTRY_NO_NATIVE=1, ``available`` is
False and every caller simply keeps using its Python version, which gives the same results.
"""

from __future__ import annotations

import ctypes
from ctypes import c_double, c_int64, c_size_t, c_uint32, POINTER
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DLL_PATH = Path(__file__).resolve().parent.parent / "native" / "sentry_native.dll"
_DOUBLE_P = POINTER(c_double)


def _load():
    if os.environ.get("SENTRY_NO_NATIVE"):
        return None, None
    try:
        # PyDLL keeps the interpreter lock, which is faster for the tiny calls; CDLL frees it for batches.
        quick, batch = ctypes.PyDLL(str(DLL_PATH)), ctypes.CDLL(str(DLL_PATH))
        for name, result, arguments in (
                ("sentry_base_height", c_double, (c_double, c_double)),
                ("sentry_height", c_double, (c_double, c_double)),
                ("sentry_surface_height", c_double, (c_double, c_double, c_int64)),
                ("sentry_paint", c_uint32, (c_double, c_double, c_double)),
                ("sentry_set_craters", None, (_DOUBLE_P, c_size_t)),
                ("sentry_terrain_setup", None, (c_double,) * 5),
                ("sentry_cape", None, (_DOUBLE_P, c_size_t, c_size_t, c_double, c_double, c_double, c_double,
                                       _DOUBLE_P, _DOUBLE_P))):
            function = getattr(quick, name)
            function.restype, function.argtypes = result, arguments
        for name, element in (("sentry_paint_many", c_uint32), ("sentry_heights", c_double)):
            function = getattr(batch, name)
            function.restype, function.argtypes = None, (_DOUBLE_P, c_size_t, POINTER(element))
        return quick, batch
    except (OSError, AttributeError) as error:  # missing, or not allowed to load
        logger.info("Compiled maths not in use (%s); using the Python versions", error)
        return None, None


_quick, _batch = _load()
available = _quick is not None

if available:
    base_height = _quick.sentry_base_height
    height = _quick.sentry_height
    surface_height = _quick.sentry_surface_height
    paint = _quick.sentry_paint
    terrain_setup = _quick.sentry_terrain_setup


def set_craters(rows: list) -> None:
    """Rows of (chunk x, chunk z, x, z, radius, depth), in the order Python keeps them."""
    flat = [value for row in rows for value in row]
    _quick.sentry_set_craters((c_double * len(flat))(*flat), len(rows))


def _flat_points(points: list):
    flat = [value for point in points for value in point]
    return (c_double * len(flat))(*flat)


def paint_many(points: list) -> list:
    """Packed 0xRRGGBB colours of the unmarked ground at many (x, z) points, on every core."""
    out = (c_uint32 * len(points))()
    _batch.sentry_paint_many(_flat_points(points), len(points), out)
    return out[:]


def heights(points: list) -> list:
    out = (c_double * len(points))()
    _batch.sentry_heights(_flat_points(points), len(points), out)
    return out[:]


class CapeGrid:
    """One character's cape, with its buffers kept so a frame allocates nothing in the native code."""

    def __init__(self, rows: int, cols: int, original: list) -> None:
        self.rows, self.cols = rows, cols
        flat = [value for vertex in original for value in vertex]
        self._original = (c_double * len(flat))(*flat)
        self._moved = (c_double * len(flat))()
        self._trim = (c_double * (rows * 12))()

    def deform(self, time: float, wind: float, forward: float, right: float) -> tuple[list, list]:
        moved, trim = self._moved, self._trim
        _quick.sentry_cape(self._original, self.rows, self.cols, time, wind, forward, right, moved, trim)
        values, edge = moved[:], trim[:]
        return (list(zip(values[0::3], values[1::3], values[2::3])),
                list(zip(edge[0::3], edge[1::3], edge[2::3])))
