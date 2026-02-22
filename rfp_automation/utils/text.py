"""
Text processing utilities with boundary awareness.
"""

import re

def truncate_at_boundary(text: str, limit: int) -> str:
    """
    Truncates text to a maximum of `limit` characters, respecting structural boundaries.
    It looks back from the limit for the nearest:
    1. Paragraph boundary (\\n\\n)
    2. Newline (\\n)
    3. Sentence end (., ?, !)
    4. Whitespace
    If no boundary is found within the last 500 characters, it forces a cut at the limit.
    """
    if len(text) <= limit:
        return text

    # We want to find a boundary within the last 500 characters of the limit
    search_window_start = max(0, limit - 500)
    window = text[search_window_start:limit]

    # Try boundaries in order of preference
    # 1. Paragraph boundary
    idx = window.rfind("\n\n")
    if idx != -1:
        return text[:search_window_start + idx + 2]

    # 2. Line boundary
    idx = window.rfind("\n")
    if idx != -1:
        return text[:search_window_start + idx + 1]

    # 3. Sentence boundary
    sentence_matches = list(re.finditer(r'[.?!](?:\s+|$)', window))
    if sentence_matches:
        last_match = sentence_matches[-1]
        return text[:search_window_start + last_match.end()]

    # 4. Whitespace boundary
    whitespace_matches = list(re.finditer(r'\s+', window))
    if whitespace_matches:
        last_match = whitespace_matches[-1]
        return text[:search_window_start + last_match.end()]

    # 5. Force cut
    return text[:limit]
