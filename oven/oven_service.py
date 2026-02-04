#!/usr/bin/env python3
import os
import time
import requests
from datetime import datetime, timezone

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_URL = f"{POUNDCAKE_API_URL}/api/v1"
OVEN_INTERVAL = int(os.getenv("OVEN_INTERVAL", "5"))


def log(message: str, req_id: str = "SYSTEM"):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [req_id: {req_id}] oven_service: {message}", flush=True)


def wait_for_api():
    """Wait for API to be ready before starting main loop."""
    log("Waiting for API to be ready")
    max_attempts = 30
    attempt = 0

    while attempt < max_attempts:
        try:
            resp = requests.get(f"{API_URL}/health", timeout=5)
            if resp.status_code == 200:
                log("API is ready! Starting dispatcher...")
                return True
        except Exception:
            pass

        attempt += 1
        if attempt < max_attempts:
            time.sleep(2)  # Check every 2 seconds

    log(f"API did not become ready after {max_attempts} attempts. Starting anyway...")
    return False


def dispatch_loop():
    wait_for_api()
    log(f"Starting dispatcher polling {API_URL}")
    while True:
        try:
            # 1. Fetch 'new' alerts
            resp = requests.get(
                f"{API_URL}/alerts", params={"processing_status": "new"}, timeout=10
            )
            resp.raise_for_status()
            alerts = resp.json()

            for alert in alerts:
                req_id = alert.get("req_id", "UNKNOWN")
                alert_id = alert.get("id")

                # PROPAGATE: Pass the original Request ID to the next hop
                headers = {"X-Request-ID": req_id}

                log(f"Triggering bake for alert_id={alert_id}", req_id=req_id)

                bake_resp = requests.post(
                    f"{API_URL}/ovens/bake/{alert_id}", headers=headers, timeout=15
                )

                if bake_resp.status_code in [200, 201]:
                    log(f"Successfully baked alert_id={alert_id} into tasks", req_id=req_id)
                else:
                    log(
                        f"Bake failed (status={bake_resp.status_code}): {bake_resp.text}",
                        req_id=req_id,
                    )

        except Exception as e:
            log(f"Loop error: {str(e)}")

        time.sleep(OVEN_INTERVAL)


if __name__ == "__main__":
    dispatch_loop()
