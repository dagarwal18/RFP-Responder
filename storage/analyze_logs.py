import json
import os
import glob
from datetime import datetime, timezone

checkpoint_dir = r"d:\My Codes\RFP-Responder\RFP-Responder\storage\checkpoints\RFP-CB810E39"
files = glob.glob(os.path.join(checkpoint_dir, "*.json"))

checkpoints = []
for f in files:
    if "pipeline_errors" in f: continue
    with open(f, 'r', encoding='utf-8') as file:
        try:
            state = json.load(file)
            saved_at_str = state.get("_checkpoint", {}).get("saved_at")
            if saved_at_str:
                dt = datetime.fromisoformat(saved_at_str.replace("Z", "+00:00"))
                agent = state.get("_checkpoint", {}).get("agent")
                checkpoints.append({"agent": agent, "time": dt, "state": state})
        except Exception as e:
            pass

checkpoints.sort(key=lambda x: x["time"])

print("--- Execution Times per Agent ---")
total_time = 0
prev_time = None

if checkpoints:
    first_state = checkpoints[0]["state"]
    received_at_str = first_state.get("rfp_metadata", {}).get("received_at")
    if received_at_str:
        try:
            prev_time = datetime.fromisoformat(received_at_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        except ValueError:
            prev_time = datetime.strptime(received_at_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

for cp in checkpoints:
    time = cp["time"]
    if prev_time:
        duration = (time - prev_time).total_seconds()
        print(f"{cp['agent']}: {duration:.2f} seconds")
        total_time += duration
    prev_time = time

print(f"\n--- Total Processing Time: {total_time:.2f} seconds ({total_time/60:.2f} min) ---")

if checkpoints:
    last_state = checkpoints[-1]["state"]
    rfp_meta = last_state.get("rfp_metadata", {})
    page_count = rfp_meta.get("page_count", 0)
    word_count = rfp_meta.get("word_count", 0)
    reqs = last_state.get("requirements", [])
    
    print(f"\n--- Analytics ---")
    print(f"Pages: {page_count}, Words: {word_count}, Requirements: {len(reqs)}")
    if total_time > 0 and page_count > 0:
        print(f"Pages per minute: {(page_count / (total_time/60)):.2f}")
        print(f"Seconds per page: {(total_time / page_count):.2f}")
