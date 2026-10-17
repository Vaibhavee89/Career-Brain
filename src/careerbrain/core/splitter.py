from __future__ import annotations

_SEPARATORS = ("\n\n", "\n", " ")


def split_message(text: str, limit: int) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be positive")

    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        cut = _find_cut(remaining, limit)
        chunk = remaining[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _find_cut(text: str, limit: int) -> int:
    for separator in _SEPARATORS:
        index = text.rfind(separator, 0, limit + 1)
        if index > 0:
            return index
    return limit
