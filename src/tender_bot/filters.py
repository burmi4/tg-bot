"""Functions to filter out unwanted tenders."""

from __future__ import annotations

from tender_bot.models import TenderItem


def is_tender_allowed(tender: TenderItem, stop_words: list[str]) -> bool:
    """Check if the tender is allowed (does not contain any stop words).
    The check is case-insensitive and examines the tender's title.
    If the title contains any of the stop words, returns False.
    Otherwise, returns True.
    """
    if not stop_words:
        return True

    title_lower = tender.title.lower()
    return all(word.lower() not in title_lower for word in stop_words)
