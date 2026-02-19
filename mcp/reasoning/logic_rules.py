from typing import List, Dict

RULES = [
    {"id": "R_BASIC_SUPPORT", "description": "Basic tier cannot claim 24/7 support", "pattern": "24/7"}
]

def check_rules(draft: str, requirement: Dict) -> List[Dict]:
    violations = []
    for r in RULES:
        if r["pattern"].lower() in draft.lower():
            violations.append({"rule_id": r["id"], "message": r["description"]})
    return violations
