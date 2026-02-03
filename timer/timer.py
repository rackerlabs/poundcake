#!/usr/bin/env python3
#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Timer Service - Monitors oven executions and updates completion status."""

#!/usr/bin/env python3
import os
import time
import requests
from datetime import datetime, timezone

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000/api/v1").rstrip('/')
ST2_API_URL = os.getenv("ST2_API_URL", "http://stackstorm-api:9101/v1").rstrip('/')
ST2_API_KEY = os.getenv("ST2_API_KEY", "")
TIMER_INTERVAL = int(os.getenv("TIMER_INTERVAL", "10"))

# System request ID for polling operations (distinguishes system calls from alert processing)
SYSTEM_REQ_ID = "SYSTEM-TIMER-POLL"

def log(message: str, req_id: str = "SYSTEM"):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [req_id: {req_id}] timer: {message}", flush=True)

def monitor_ovens():
    headers = {"Content-Type": "application/json"}
    if ST2_API_KEY:
        headers["St2-Api-Key"] = ST2_API_KEY

    try:
        # 1. Get ovens currently in flight (system operation, not tied to specific alert)
        resp = requests.get(
            f"{POUNDCAKE_API_URL}/ovens", 
            params={"processing_status": "processing"}, 
            headers={"X-Request-ID": SYSTEM_REQ_ID},
            timeout=10
        )
        ovens = resp.json()

        for oven in ovens:
            # Switch from system polling req_id to alert's req_id for all subsequent operations
            # This ensures end-to-end traceability for this specific alert
            req_id = oven.get("req_id", "UNKNOWN")
            action_id = oven.get("action_id")

            # Add trace ID to all monitoring calls
            headers["X-Request-ID"] = req_id

            # 2. Check ST2 Status
            st2_resp = requests.get(f"{ST2_API_URL}/executions/{action_id}", headers=headers, timeout=10)
            if st2_resp.status_code == 200:
                st2_data = st2_resp.json()
                
                # Ensure response is a dict, not a string
                if not isinstance(st2_data, dict):
                    log(f"Unexpected ST2 response type for action {action_id}: {type(st2_data)}", req_id=req_id)
                    continue
                    
                st2_status = st2_data.get("status")

                # 3. If finished, update API
                if st2_status in ["succeeded", "failed", "canceled"]:
                    new_status = "complete"
                    requests.put(
                        f"{POUNDCAKE_API_URL}/ovens/{oven.get('id')}",
                        json={"processing_status": new_status, "st2_status": st2_status},
                        headers=headers,
                        timeout=10
                    )
                    log(f"Oven {oven.get('id')} marked {new_status} (ST2: {st2_status})", req_id=req_id)

    except Exception as e:
        log(f"Error in monitor loop: {str(e)}")

if __name__ == "__main__":
    while True:
        monitor_ovens()
        time.sleep(TIMER_INTERVAL)
