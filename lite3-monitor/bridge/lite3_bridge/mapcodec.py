"""Occupancy-grid encoding for the websocket.

Input is the raw int8 OccupancyGrid payload as bytes (-1 == 0xFF unknown,
0 free, 1..100 occupancy probability). Output is a JSON-able dict with the
grid cropped to its known bounding box, zlib-compressed and base64-encoded.
The browser inflates it with DecompressionStream('deflate').
"""
from __future__ import annotations

import base64
import math
import zlib
from typing import Any, Dict, Optional, Tuple

UNKNOWN = 0xFF
OCCUPIED_THRESHOLD = 65  # same default as map_server occupied_thresh 0.65


def grid_stats(data: bytes, resolution: float, arena_area_m2: Optional[float]) -> Dict[str, Any]:
    total = len(data)
    unknown = data.count(UNKNOWN)
    free = data.count(0)
    occupied = 0
    for v in range(OCCUPIED_THRESHOLD, 101):
        occupied += data.count(v)
    known = total - unknown
    cell_area = resolution * resolution
    free_area = free * cell_area
    coverage_pct = None
    if arena_area_m2:
        coverage_pct = min(100.0, 100.0 * free_area / float(arena_area_m2))
    return {
        "total_cells": total,
        "free_cells": free,
        "occupied_cells": occupied,
        "unknown_cells": unknown,
        "known_area_m2": round(known * cell_area, 2),
        "free_area_m2": round(free_area, 2),
        "known_fraction": round(known / total, 4) if total else 0.0,
        "coverage_pct": None if coverage_pct is None else round(coverage_pct, 2),
    }


def known_bbox(data: bytes, width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
    """Return (x0, y0, x1, y1) inclusive bbox of non-unknown cells, or None."""
    if width <= 0 or height <= 0:
        return None
    y0 = y1 = None
    for y in range(height):
        row = data[y * width:(y + 1) * width]
        if row.count(UNKNOWN) != width:
            if y0 is None:
                y0 = y
            y1 = y
    if y0 is None:
        return None
    x0, x1 = width, -1
    for y in range(y0, y1 + 1):
        row = data[y * width:(y + 1) * width]
        if row.count(UNKNOWN) == width:
            continue
        # first / last known column in this row
        stripped_left = len(row) - len(row.lstrip(b"\xff"))
        stripped_right = len(row.rstrip(b"\xff"))
        x0 = min(x0, stripped_left)
        x1 = max(x1, stripped_right - 1)
    return x0, y0, x1, y1


def encode_map(
    data: bytes,
    width: int,
    height: int,
    resolution: float,
    origin_x: float,
    origin_y: float,
    origin_yaw: float,
    frame: str,
    arena_area_m2: Optional[float] = None,
    pad: int = 4,
) -> Dict[str, Any]:
    if len(data) != width * height:
        raise ValueError(f"map payload {len(data)} != {width}x{height}")
    stats = grid_stats(data, resolution, arena_area_m2)
    crop = None
    # Cropping is only exact when the map origin is axis-aligned.
    if abs(origin_yaw) < 1e-6:
        crop = known_bbox(data, width, height)
    if crop is not None:
        x0, y0, x1, y1 = crop
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(width - 1, x1 + pad)
        y1 = min(height - 1, y1 + pad)
        cw, ch = x1 - x0 + 1, y1 - y0 + 1
        rows = [data[(y * width + x0):(y * width + x0 + cw)] for y in range(y0, y1 + 1)]
        payload = b"".join(rows)
        ox = origin_x + x0 * resolution
        oy = origin_y + y0 * resolution
    else:
        cw, ch, payload, ox, oy = width, height, data, origin_x, origin_y
    compressed = zlib.compress(payload, 3)
    return {
        "frame": frame,
        "resolution": resolution,
        "width": cw,
        "height": ch,
        "full_width": width,
        "full_height": height,
        "origin": {"x": ox, "y": oy, "yaw": origin_yaw},
        "encoding": "zlib+base64",
        "data": base64.b64encode(compressed).decode("ascii"),
        "stats": stats,
        "bytes_compressed": len(compressed),
    }


def int8_to_bytes(values) -> bytes:
    """Convert an int8 sequence (rclpy array('b') or list) to raw bytes."""
    if hasattr(values, "tobytes"):
        return values.tobytes()
    return bytes((v & 0xFF) for v in values)


def finite(v: float) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)
