import os

filepath = 'd:/My Codes/RFP-Responder/RFP-Responder/rfp_automation/orchestration/transitions.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """    if decision == "BLOCK":
        return "end_legal_block"
    return "h1_human_validation_prepare\""""

new_block = """    if decision == "BLOCK":
        logger.warning(
            "[ROUTING] Commercial/Legal returned BLOCK — bypassing termination, "
            "continuing pipeline to Human Validation for testing."
        )
    return "h1_human_validation_prepare\""""

if 'return "end_legal_block"' in content:
    content = content.replace(old_block, new_block)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Patched successfully")
else:
    print("Target not found or already patched")
