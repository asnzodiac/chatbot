import os


def load_character_prompt(path: str = "character.txt") -> str:
    # Never hardcode personality: always load from file
    if not os.path.exists(path):
        return (
            "You are a helpful assistant.\n"
            "Note: character.txt not found; using minimal default."
        )

    with open(path, "r", encoding="utf-8") as f:
        txt = f.read().strip()

    return txt or "You are a helpful assistant."
