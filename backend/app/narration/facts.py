"""What the narrator is allowed to see, and the template summary used when it is off or fails.

Only the findings' own text goes out: titles, statements, importance, coverage dates, and file
caveats. Never CSV rows, order IDs, column names, line numbers, or not-assessed reasons (which can
quote line numbers). Any "(lines 4, 7, ...)" evidence is stripped as a second line of defence.
"""

import re

from app.analytics.insights import UNITS, SalesInsights

LINE_REFERENCES = re.compile(r"\s*\(lines? [0-9][0-9, .]*\)")
TEMPLATE_FINDINGS = 3


def _clean(text: str) -> str:
    return LINE_REFERENCES.sub("", text)


def build_facts(insights: SalesInsights) -> dict:
    coverage = insights.coverage
    return {
        "compared_by": insights.grain,
        "coverage": {
            "first_date": coverage.first_date.isoformat() if coverage.first_date else None,
            "last_date": coverage.last_date.isoformat() if coverage.last_date else None,
            "complete_periods": coverage.complete_periods,
        },
        "findings": [
            {"importance": item.importance, "title": _clean(item.title), "statement": _clean(item.statement)}
            for item in insights.insights
        ],
        "caveats": [_clean(caveat) for caveat in insights.caveats],
    }


def template_summary(insights: SalesInsights) -> str:
    """A deterministic summary: the top findings' own sentences."""
    if not insights.insights:
        return "There are no findings to summarize for this file."
    statements = " ".join(_clean(item.statement) for item in insights.insights[:TEMPLATE_FINDINGS])
    return f"Key findings by {UNITS[insights.grain][0]}: {statements}"
