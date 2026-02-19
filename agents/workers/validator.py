from typing import Dict, List
from mcp.reasoning.logic_rules import check_rules

async def validate_requirement(draft: str, requirement: Dict) -> Dict:
	"""
	Run neuro-symbolic validation:
	1) Check for presence of required evidence coordinates.
	2) Run symbolic rule engine for hard constraint violations.
	3) Return structured validation result with reasoning trace.
	"""
	violations: List[Dict] = []

	# Evidence coordinate verification
	evidence = requirement.get("evidence") or {}
	evidence_ok = True
	if not evidence.get("page") or not evidence.get("text"):
		evidence_ok = False
		violations.append({"type": "EVIDENCE_MISSING", "message": "Missing page or text anchor in evidence."})
	# Optionally check snippet length
	elif len(evidence.get("text", "")) < 10:
		evidence_ok = False
		violations.append({"type": "EVIDENCE_TOO_SHORT", "message": "Evidence snippet is too short to verify claims."})

	# Symbolic rule checks
	rule_violations = check_rules(draft, requirement)
	for rv in rule_violations:
		violations.append({"type": "RULE_VIOLATION", "rule_id": rv.get("rule_id"), "message": rv.get("message")})

	# Determine overall status
	logic_status = "FAILED" if violations else "PASSED"

	# Compose reasoning trace
	trace_parts = []
	trace_parts.append(f"Evidence verification: {'ok' if evidence_ok else 'failed'}")
	if rule_violations:
		trace_parts.append(f"Symbolic rule violations: {len(rule_violations)} detected")
	trace = "; ".join(trace_parts)

	result = {
		"logic_status": logic_status,
		"violations": violations,
		"reasoning_trace": trace,
		"evidence_verified": evidence_ok
	}
	return result
