import json
import re
from pathlib import Path
import sys

# Add root project path to Python path so we can import rfp_automation
project_root = Path("d:/RFP-Responder-1").resolve()
sys.path.insert(0, str(project_root))

from rfp_automation.agents.architecture_agent import ArchitecturePlanningAgent
from rfp_automation.models.schemas import ResponseSection

agent = ArchitecturePlanningAgent()

# Load state before programmatic assign
state_path = Path("d:/RFP-Responder-1/storage/checkpoints/RFP-3B68B56C/b2_requirements_validation.json")
try:
    with open(state_path, "r", encoding="utf-8") as f:
        state_data = json.load(f)
except Exception as e:
    print(f"Failed to load b2 state: {e}")
    sys.exit(1)

reqs = state_data.get("requirements_validation", {}).get("validated_requirements", [])
if not reqs:
    reqs = state_data.get("requirements", [])

print(f"Loaded {len(reqs)} requirements.")

sections = [
    ResponseSection(
        section_id="SEC-01",
        title="SECTION 5 — Technical and Functional Requirements",
        section_type="requirement_driven",
        description="Technical and functional requirements",
        requirement_ids=[],
        mapped_capabilities=[],
        priority=1
    ),
    ResponseSection(
        section_id="SEC-02",
        title="SECTION 5 — Technical and Functional Requirements > 5.2  Requirements Matrix",
        section_type="requirement_driven",
        description="Requirements Matrix",
        requirement_ids=[],
        mapped_capabilities=[],
        priority=2
    )
]

print("Running programmatic assign...")
final_sections = agent._programmatic_assign(reqs, sections)
final_sections = agent._split_overloaded_sections(reqs, final_sections)

for s in final_sections:
    print(f"{s.section_id}: {s.title} ({len(s.requirement_ids)} reqs)")
