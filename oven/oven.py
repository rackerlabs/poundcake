#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Oven Executor: Polls the API and triggers StackStorm via Bridge."""

import os
import time
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Config: No ST2 keys required here!
API_BASE_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000/api/v1")
POLL_INTERVAL = int(os.getenv("OVEN_POLL_INTERVAL", "5"))

# System request ID for polling operations (distinguishes system calls from alert processing)
SYSTEM_REQ_ID = "SYSTEM-OVEN-POLL"

def run_executor():
    logger.info("Oven Executor started. Target API: %s", API_BASE_URL)
    
    while True:
        try:
            # 1. Fetch next 'new' oven task (system operation, not tied to specific alert)
            resp = requests.get(
                f"{API_BASE_URL}/ovens", 
                params={"processing_status": "new", "limit": 1},
                headers={"X-Request-ID": SYSTEM_REQ_ID}
            )
            resp.raise_for_status()
            tasks = resp.json()

            if not tasks:
                time.sleep(POLL_INTERVAL)
                continue

            task = tasks[0]
            oven_id = task['id']
            # Switch from system polling req_id to alert's req_id for all subsequent operations
            # This ensures end-to-end traceability for this specific alert
            req_id = task['req_id']
            
            # Get ingredient details (includes st2_action and parameters)
            ingredient = task.get('ingredient', {})
            action_ref = ingredient.get('st2_action')
            parameters = ingredient.get('parameters', {})

            if not action_ref:
                logger.error("[%s] No action_ref found for Oven ID %s", req_id, oven_id)
                time.sleep(POLL_INTERVAL)
                continue

            # Add req_id to parameters for traceability
            parameters['req_id'] = req_id
            
            # 2. Proxy the request through the API Bridge
            logger.info("[%s] Triggering %s via API bridge", req_id, action_ref)
            bridge_resp = requests.post(
                f"{API_BASE_URL}/stackstorm/execute",
                json={
                    "action": action_ref,
                    "parameters": parameters
                },
                headers={"X-Request-ID": req_id},
                timeout=30
            )

            if bridge_resp.status_code == 200:
                st2_data = bridge_resp.json()
                st2_id = st2_data.get('id')
                
                # 3. Update task status
                requests.patch(
                    f"{API_BASE_URL}/ovens/{oven_id}",
                    json={
                        "processing_status": "processing", 
                        "action_id": st2_id
                    },
                    headers={"X-Request-ID": req_id}
                )
                logger.info("[%s] Action started. ST2 ID: %s", req_id, st2_id)
            else:
                logger.error("[%s] API Bridge failed: %s", req_id, bridge_resp.text)

        except Exception as e:
            logger.error("Executor loop encountered an error: %s", str(e))
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_executor()
