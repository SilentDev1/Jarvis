import re

ALLOWED_ACTIONS = {
    "none",
    "capture_photo",
    "request_badge",
    "notify_homeowner",
    "mark_delivery",
    "ask_visitor_to_wait",
    "end_session",
}
INJECTION = re.compile(
    r"(?i)(ignore|override|disregard).{0,40}(instructions|policy|prompt)|run\s+(?:a\s+)?command|system\s+prompt|shell|sudo|rm\s+-rf|unlock|disable\s+(?:the\s+)?alarm"
)


def sanitize(value: str, limit=1000):
    return "".join(c for c in value[:limit] if c in "\n\t" or ord(c) >= 32).strip()


def authorize(action: str):
    return action if action in ALLOWED_ACTIONS else "none"


def is_injection(value: str):
    return bool(INJECTION.search(sanitize(value)))
