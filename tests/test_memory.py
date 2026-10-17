import pytest

from careerbrain.core.memory import ConversationMemory, Message, estimate_tokens


def _one_token(_: str) -> int:
    return 1


def test_trims_oldest_messages_to_budget() -> None:
    memory = ConversationMemory(max_tokens=2, count_tokens=_one_token)
    memory.add_user("u1")
    memory.add_assistant("a1")
    memory.add_user("u2")
    assert memory.messages() == [Message("user", "u2")]


def test_never_starts_with_orphaned_assistant_turn() -> None:
    memory = ConversationMemory(max_tokens=3, count_tokens=_one_token)
    memory.add_user("u1")
    memory.add_assistant("a1")
    memory.add_user("u2")
    memory.add_assistant("a2")
    assert memory.messages() == [Message("user", "u2"), Message("assistant", "a2")]


def test_reset_clears_history() -> None:
    memory = ConversationMemory(max_tokens=100, count_tokens=_one_token)
    memory.add_user("hello")
    memory.add_assistant("hi")
    memory.reset()
    assert memory.messages() == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/reset", True),
        ("  /RESET please", True),
        ("hey /reset", False),
        ("resetting things", False),
    ],
)
def test_is_reset_command_matches_prefix_at_start(text: str, expected: bool) -> None:
    memory = ConversationMemory(max_tokens=10)
    assert memory.is_reset_command(text) is expected


def test_custom_reset_prefix() -> None:
    memory = ConversationMemory(max_tokens=10, reset_prefix="!clear")
    assert memory.is_reset_command("!clear now")
    assert not memory.is_reset_command("/reset")


def test_rejects_non_positive_budget() -> None:
    with pytest.raises(ValueError):
        ConversationMemory(max_tokens=0)


def test_default_estimate_is_about_four_chars_per_token() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcdefgh") == 2


def test_default_counter_trims_by_characters() -> None:
    memory = ConversationMemory(max_tokens=3)
    memory.add_user("x" * 8)
    memory.add_assistant("y" * 8)
    memory.add_user("z" * 4)
    assert memory.messages() == [Message("user", "z" * 4)]


def test_oversized_message_is_dropped() -> None:
    memory = ConversationMemory(max_tokens=2, count_tokens=lambda text: len(text))
    memory.add_user("way too long for the budget")
    assert memory.messages() == []
