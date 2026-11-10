"""Suggested starter questions for the New Conversation screen (story 3.1).

Placeholder content taken from the story's examples, until The Oracle's team supplies the
lists. They're built here rather than asked of the Oracle, so nothing about the profile reaches
the AI service before its Health Consent is accepted, and opening the screen costs nothing.
"""


def starter_questions(is_self: bool, first_name: str) -> list[str]:
    if is_self:
        return [
            "Why am I so exhausted all the time?",
            "My labs look normal but I feel terrible",
            "Hormone imbalance",
        ]
    return [
        f"Why is {first_name} so exhausted all the time?",
        f"{first_name}’s labs look normal, but something feels off",
        "Hormone imbalance",
    ]
