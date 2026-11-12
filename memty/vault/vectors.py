"""Portable float32 vector packing used by rolling summaries and facts."""

from __future__ import annotations

import math
from array import array


def pack_vector(vector: list[float]) -> bytes:
    values = [float(value) for value in vector]
    if not values or len(values) > 32768:
        raise ValueError("embedding must contain 1 to 32768 values")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding values must be finite")
    return array("f", values).tobytes()


def unpack_vector(blob: bytes | memoryview | None) -> list[float]:
    if not blob:
        return []
    values = array("f")
    values.frombytes(bytes(blob))
    return [float(value) for value in values]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norm if norm else 0.0
