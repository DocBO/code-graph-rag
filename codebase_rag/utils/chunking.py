"""Chunking helpers shared between embedding generation and retrieval."""

from __future__ import annotations


def chunk_boundaries(code_length: int, max_size: int) -> list[tuple[int, int]]:
    """Return (start, end) pairs that partition ``code_length`` characters.

    Chunks are evenly sized (differing by at most one character) so the final
    chunk is never a tiny tail remainder below half of ``max_size``. A
    ``code_length`` at or below ``max_size`` yields a single chunk covering the
    whole input.
    """
    if code_length <= 0 or max_size <= 0:
        return []
    chunk_count = (code_length + max_size - 1) // max_size
    base, extra = divmod(code_length, chunk_count)
    boundaries: list[tuple[int, int]] = []
    start = 0
    for i in range(chunk_count):
        size = base + (1 if i < extra else 0)
        boundaries.append((start, start + size))
        start += size
    return boundaries
