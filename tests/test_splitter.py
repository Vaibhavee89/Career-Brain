import pytest

from careerbrain.core.splitter import split_message


def test_short_text_is_one_chunk() -> None:
    assert split_message("hello world", 50) == ["hello world"]


def test_empty_text_returns_no_chunks() -> None:
    assert split_message("   ", 10) == []


def test_prefers_paragraph_boundary() -> None:
    text = "first paragraph\n\nsecond paragraph"
    assert split_message(text, 20) == ["first paragraph", "second paragraph"]


def test_falls_back_to_line_then_word_boundary() -> None:
    assert split_message("aaaa\nbbbb cccc", 9) == ["aaaa", "bbbb cccc"]
    assert split_message("aaaa bbbb cccc", 9) == ["aaaa bbbb", "cccc"]


def test_hard_splits_word_longer_than_limit() -> None:
    assert split_message("abcdefghij", 4) == ["abcd", "efgh", "ij"]


def test_every_chunk_respects_limit() -> None:
    text = ("lorem ipsum dolor sit amet " * 200).strip()
    chunks = split_message(text, 2000)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert len(chunks) > 1


def test_no_content_is_lost() -> None:
    words = [f"word{i}" for i in range(500)]
    text = " ".join(words)
    chunks = split_message(text, 100)
    assert " ".join(chunks).split() == words


def test_text_exactly_at_limit_is_one_chunk() -> None:
    assert split_message("abcdefghij", 10) == ["abcdefghij"]


def test_separator_at_exact_limit_boundary() -> None:
    assert split_message("abcd efgh", 9) == ["abcd efgh"]
    assert split_message("abcd efgh", 8) == ["abcd", "efgh"]


def test_multiple_blank_lines_do_not_yield_empty_chunks() -> None:
    chunks = split_message("one\n\n\n\ntwo\n\n\n\nthree", 5)
    assert chunks == ["one", "two", "three"]


@pytest.mark.parametrize("limit", [0, -1])
def test_rejects_non_positive_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        split_message("anything", limit)
