PROMPT_ADAPT = """Given requirement:
{requirement_text}

Given example answer:
{example_answer}

Instructions:
- Adapt the example to fit the new requirement.
- Do NOT add facts that are not supported by the evidence anchor.
- Keep the answer concise (1-3 sentences) and include an explicit evidence anchor reference.

Adapted draft:
"""
# future templates could be added here (validation prompts, rephrasing, summarization)
