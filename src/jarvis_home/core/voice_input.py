import re

NOISE_ONLY = re.compile(
    r"^\s*(?:\[(?:noise|silence|music|inaudible)\]|\((?:noise|silence|music|inaudible)\)|[.?!,_-]*)\s*$",
    re.IGNORECASE,
)


def is_meaningful_utterance(text: str | None) -> bool:
    """Conservative gate for adapters that receive an actual transcript."""
    if not text or NOISE_ONLY.fullmatch(text):
        return False
    normalized = "".join(character for character in text if character.isalnum())
    return len(normalized) >= 2
