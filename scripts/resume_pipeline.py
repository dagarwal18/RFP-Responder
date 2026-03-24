import json
import logging
import sys
from rfp_automation.orchestration.graph import run_pipeline_from

logging.basicConfig(level=logging.INFO)

rfp_id = "RFP-18CD311A"
checkpoint_path = f"d:/RFP-Responder-1/storage/checkpoints/{rfp_id}/b2_requirements_validation.json"

if __name__ == "__main__":
    print(f"Loading checkpoint from: {checkpoint_path}")
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        
        run_pipeline_from("c1_architecture_planning", state)
        print("Pipeline run completed from C1!")
    except Exception as e:
        print(f"Error running pipeline: {e}")
        import traceback
        traceback.print_exc()
