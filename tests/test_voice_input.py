import pytest

from jarvis_home.core.voice_input import is_meaningful_utterance


@pytest.mark.parametrize(
    "text", [None, "", "   ", "...", "[noise]", "(silence)", "[inaudible]", "a"]
)
def test_empty_or_noise_only_input_is_rejected(text):
    assert not is_meaningful_utterance(text)


@pytest.mark.parametrize(
    "text", ["Hi", "Jarvis", "Is anyone at the door?", "status please"]
)
def test_meaningful_input_is_accepted(text):
    assert is_meaningful_utterance(text)
