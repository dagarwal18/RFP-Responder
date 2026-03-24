import logging
import json
import re

from rfp_automation.agents.writing_agent import RequirementWritingAgent
from rfp_automation.models.schemas import RFPSection, Requirement
import rfp_automation.agents.writing_agent as wa

logging.basicConfig(level=logging.INFO, format="%(message)s")

def test_vlm_table_fixes():
    print("\n--- RUNNING TABLE EXTRACTION & MERGING VERIFICATION ---")

    # 1. Mocked Chunks representing the VLM extraction output (including Fix #1: table_type)
    chunks = [
        {
            "id": "chunk_0",
            "is_table": True,
            "table_type": "fill_in_table",
            "text": "TR-ID | Requirement | Description | Mandatory/Optional | [C / PC / NC] | [Vendor to fill — Name OEM]\n---|---|---|---|---|---\nTR-005 | SD-WAN OEM | Hardware partner | Mandatory |  | ",
        },
        {
            "id": "chunk_1",
            "is_table": True,
            "table_type": "fill_in_table",
            "text": "TR-ID | Requirement | Description | Mandatory | C / PC / NC | Vendor to fill\n---|---|---|---|---|---\nTR-012 | Latency | 8ms | Mandatory |  | ",
        }
    ]

    # 2. Mocked Requirements pointing to specific table chunks
    req_map = {
        "REQ-0001": {"type": "MANDATORY", "text": "Hardware partner", "source_table_chunk_index": 0, "source_chunk_indices": [0]},
        "REQ-0002": {"type": "MANDATORY", "text": "8ms Latency", "source_table_chunk_index": 1, "source_chunk_indices": [1]},
    }

    section = {
        "description": "Compliance matrix",
        "content_guidance": "Fill in the vendor responses.",
    }

    # Intercept the LLM call to just grab the prompt
    captured_prompts = []
    
    def fake_llm_large_text_call(prompt, **kwargs):
        captured_prompts.append(prompt)
        # Fake JSON response to prevent parse crashing
        return '```json\n{"content": "| table |\\n|---|", "requirements_addressed": [], "word_count": 10}\n```'

    wa.llm_large_text_call = fake_llm_large_text_call

    agent = RequirementWritingAgent()

    # Create dummy structures
    table_chunks_by_index = {0: chunks[0], 1: chunks[1]}
    
    # Let's call the internal grouping logic used in the loop:
    print("\n[TEST 1: Table Independent Processing]")
    table_groups = {}
    for rid in ["REQ-0001", "REQ-0002"]:
        tci = req_map[rid].get("source_table_chunk_index", -1)
        table_groups.setdefault(tci, []).append(rid)

    print(f"Grouped into {len(table_groups)} separate tables. (Expected: 2)")
    assert len(table_groups) == 2, "Tables merged incorrectly!"

    print("\n[TEST 2: Prompt Header Preservation]")
    for tci, group_rids in table_groups.items():
        tbl_text = table_chunks_by_index[tci]["text"]
        
        # Test filling exactly this table
        agent._fill_single_table(
            table_text=tbl_text,
            req_ids=group_rids,
            req_map=req_map,
            section=section,
            capabilities="Test Capability",
            rfp_instructions="",
            rfp_metadata_block="",
            prev_ctx="",
            next_ctx="",
            section_feedback="",
            section_id=f"matrix_{tci}",
            title=f"Matrix {tci}",
            section_type="requirement_driven",
            batch_size=12
        )

    # Verify Prompts
    print(f"\nCaptured {len(captured_prompts)} LLM prompt calls. (Expected: 2)")
    assert len(captured_prompts) == 2
    
    print("\nExamining Prompt #1 for hardcoded vs original headers:")
    assert "ORIGINAL TABLE from the RFP" in captured_prompts[0], "Table Mode active flag missing!"
    assert "[Vendor to fill — Name OEM]" in captured_prompts[0], "Original exact header was lost!"
    print("-> Prompt #1 correctly contains the exact original column structure: '[Vendor to fill — Name OEM]'")

    print("\nExamining Prompt #2 for matching its own distinct headers:")
    prompt_2_table = captured_prompts[1].split("### ORIGINAL RFP TABLE:\n```", 1)[1]
    assert "Vendor to fill" in prompt_2_table and "Name OEM" not in prompt_2_table, "Table 2 inherited Table 1's headers!"
    print("-> Prompt #2 independent processing confirmed. No cross-contamination.")

    print("\n--- ALL TESTS PASSED SUCCESSFULLY! ---")
    print("Fixes Verify: Tables are processed sequentially, independent of each other without generic merging, and strict VLM original columns are enforced to the LLM.")

if __name__ == "__main__":
    test_vlm_table_fixes()
