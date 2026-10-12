"""Checks a narrator's text against the findings it was given. Its output is untrusted.

A summary passes only if it is short plain text, claims no cause and makes no prediction, and
every number and every quoted name in it appears in the findings. Anything else is rejected and
the template summary is shown instead.
"""

import json
import re
from decimal import Decimal, InvalidOperation

MAX_CHARACTERS = 900

CAUSAL = re.compile(
    r"\b(because|due to|caused|causes|causing|driven by|drove|drives|led to|leads to|resulted in|results in|"
    r"as a result|thanks to|owing to|attributable|attributed|stemm(?:ed|ing) from)\b",
    re.IGNORECASE,
)
PREDICTION = re.compile(
    r"\b(will|forecast|forecasts|predict|predicts|predicted|expected to|likely to|projected|going to|should continue)\b",
    re.IGNORECASE,
)
MARKUP = re.compile(r"https?://|www\.|<[a-z/][^>]*>|\*\*|__|`|^\s*#|^\s*[-*] |\[[^\]]*\]\(", re.IGNORECASE | re.MULTILINE)
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
QUOTED = re.compile(r"(?<![\w])'([^'\n]+)'(?![\w])")


def _value(token: str) -> Decimal | None:
    try:
        return abs(Decimal(token.replace(",", "").rstrip("%"))).normalize()
    except InvalidOperation:
        return None


def check_narration(text: str, facts: dict) -> list[str]:
    """Problems with the text, or [] when it may be shown."""
    if not text.strip():
        return ["The summary is empty."]
    problems: list[str] = []
    if len(text) > MAX_CHARACTERS:
        problems.append(f"The summary is too long ({len(text)} characters; at most {MAX_CHARACTERS}).")
    if MARKUP.search(text):
        problems.append("The summary must be plain text (no links, formatting, or markup).")
    if match := CAUSAL.search(text):
        problems.append(f"The summary claims a cause ('{match.group(0)}').")
    if match := PREDICTION.search(text):
        problems.append(f"The summary makes a prediction ('{match.group(0)}').")

    source = json.dumps(facts, ensure_ascii=False)
    allowed = {value for token in NUMBER.findall(source) if (value := _value(token)) is not None}
    for token in NUMBER.findall(text):
        if _value(token) not in allowed:
            problems.append(f"A number is not in the findings: {token}.")
            break  # one example is enough; the summary is rejected either way
    known_names = set(QUOTED.findall(source))
    for name in QUOTED.findall(text):
        if name not in known_names:
            problems.append(f"A name is not in the findings: '{name}'.")
            break
    return problems
