from typing import Dict
from mcp.reasoning.cbr_engine import find_similar_cases
from agents.prompts.templates import PROMPT_ADAPT

async def adapt_with_cbr(requirement: Dict) -> str:
	"""
	Query CBR engine, then produce a short adapted draft.
	- Attach cbr_citation into returned draft via metadata in the string header.
	- Does not call external LLMs here; instead uses a safe templated adaptation combining
	  the requirement and the highest-scoring similar case.
	"""
	text = requirement.get("description", "") or requirement.get("title", "")
	sims = await find_similar_cases(text, k=3)
	if not sims:
		# No similar cases, produce conservative draft anchored to evidence
		draft = f"(No similar case) Proposed response: We confirm the requirement as described. Evidence: page {requirement.get('evidence',{}).get('page')}"
		return draft

	# pick top case
	top = sims[0]
	case_id = top.get("case_id", "CASE_UNKNOWN")
	example = top.get("answer_snippet", "")
	# simple templating without introducing new facts
	draft_body = PROMPT_ADAPT.format(requirement_text=text, example_answer=example)
	# Compose final adapted draft (short)
	draft = f"[CBR:{case_id}] " + _shorten_adaptation(draft_body, max_len=800)
	return draft

def _shorten_adaptation(text: str, max_len: int = 800) -> str:
	# remove excessive whitespace and truncate politely
	t = " ".join(text.split())
	if len(t) <= max_len:
		return t
	return t[:max_len-3].rstrip() + "..."
