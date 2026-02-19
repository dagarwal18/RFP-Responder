import datetime
def log_audit(event: str, payload: dict):
    print(f"[AUDIT] {datetime.datetime.utcnow().isoformat()} {event} {payload}")
