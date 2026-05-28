"""Deterministic keyword tagger — source of truth for news pause decisions.

LLM tagger is advisory only; this module controls actual risk pauses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HIGH_IMPACT_NEGATIVE_PATTERNS: dict[str, list[str]] = {
    "regulatory": [
        r"\bban\b", r"\bcrackdown\b", r"\billegal\b", r"\bprohibit", r"\bsec\s+sues",
        r"\benforcement\b", r"\bsanction", r"\bblacklist",
    ],
    "hack": [
        r"\bhack(ed|ing)?\b", r"\bexploit(ed)?\b", r"\bstolen\b", r"\bdrained\b",
        r"\bbreach\b", r"\bcompromis(ed|e)\b", r"\b\$\d+[mMbB]\s+(stolen|lost|exploit)",
    ],
    "exchange-outage": [
        r"\bdown\b.*\bexchange\b", r"\boutage\b", r"\bwithdrawal\s+halt", r"\btrading\s+halt",
        r"\bmaintenance\b.*\bhalt", r"\bfreezes?\s+withdrawal",
    ],
    "macro-event": [
        r"\bfomc\b", r"\binterest\s+rate\s+(hike|cut|decision)\b",
        r"\brecession\b", r"\bcpi\b.*\bsurprise", r"\bblack\s+swan\b",
    ],
}

HIGH_IMPACT_POSITIVE_PATTERNS: dict[str, list[str]] = {
    "etf-flow": [
        r"\betf\s+(approval|launch|inflow|record)\b", r"\bspot\s+bitcoin\s+etf\b",
        r"\binstitutional\s+(buying|accumulation)\b",
    ],
}


@dataclass
class TagResult:
    tags: list[str]
    sentiment: float  # -1 to +1
    is_high_impact_negative: bool


def tag_item(title: str, body: str = "") -> TagResult:
    text = (title + " " + body).lower()
    tags: list[str] = []
    is_negative = False

    for tag, patterns in HIGH_IMPACT_NEGATIVE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                tags.append(tag)
                is_negative = True
                break

    is_positive = False
    for tag, patterns in HIGH_IMPACT_POSITIVE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                tags.append(tag)
                is_positive = True
                break

    sentiment = -0.8 if is_negative else (0.6 if is_positive else 0.0)
    return TagResult(tags=list(set(tags)), sentiment=sentiment, is_high_impact_negative=is_negative)
