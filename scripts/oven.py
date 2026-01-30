#!/usr/bin/env python3
#  ____                       _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Oven Service - Starts StackStorm executions for ready ovens."""

import os
import time
import requests
from datetime import datetime
from typing import List, Dict, Any

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000")
OVEN_INTERVAL = int(os.getenv("OVEN_INTERVAL", "5"))
ST2_API_URL = os.getenv("ST2_API_URL", "http://st2api:9101/v1")
ST2_API_KEY = os.getenv("ST2_API_KEY", "")


def log(function: str, message: str, **kwargs):
    """Structured logging with function name."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
    extra_str = f" [{extra}]" if extra else ""
    print(f"[{timestamp}] oven.{function}: {message}{extra_str}", flush=True)


def oven_loop():
    """Main oven loop - runs continuously on schedule."""
    log("oven_loop", f"Oven service started", interval=f"{OVEN_INTERVAL}s")
    log("oven_loop", f"Configuration", api=POUNDCAKE_API_URL, st2=ST2_API_URL)
    
    while True:
        try:
            log("oven_loop", "=== Cycle started ===")
            start_ready_ovens()
            log("oven_loop", "=== Cycle complete ===\n")
        except Exception as e:
            log("oven_loop", f"ERROR: {e}")
            import traceback
            traceback.print_exc()
        
        time.sleep(OVEN_INTERVAL)


def start_ready_ovens():
    """Find ovens with status='new' and start if ready."""
    try:
        response = requests.get(
            f"{POUNDCAKE_API_URL}/api/v1/ovens",
            params={"processing_status": "new"},
            timeout=10
        )
        response.raise_for_status()
        ovens = response.json()
        
        if not ovens:
            log("start_ready_ovens", "No ovens in new state")
            return
        
        log("start_ready_ovens", f"Found ovens to start", count=len(ovens))
        
        ovens_by_req = {}
        for oven in ovens:
            req_id = oven.get("req_id")
            if req_id not in ovens_by_req:
                ovens_by_req[req_id] = []
            ovens_by_req[req_id].append(oven)
        
        for req_id, req_ovens in ovens_by_req.items():
            process_request_ovens(req_id, req_ovens)
    except Exception as e:
        log("start_ready_ovens", f"ERROR: {e}")


def process_request_ovens(req_id: str, new_ovens: List[Dict[str, Any]]):
    """Process ovens for a specific request, respecting is_blocking."""
    try:
        response = requests.get(
            f"{POUNDCAKE_API_URL}/api/v1/executions/{req_id}",
            timeout=10
        )
        response.raise_for_status()
        all_ovens = response.json()
        
        log("process_request_ovens", "Processing request ovens", 
            req_id=req_id, new_count=len(new_ovens), total_count=len(all_ovens))
        
        for oven in new_ovens:
            if can_start_oven(oven, all_ovens):
                start_oven(oven)
            else:
                log("process_request_ovens", "Waiting for dependencies", 
                    oven_id=oven['id'], task_order=oven['task_order'])
    except Exception as e:
        log("process_request_ovens", f"ERROR: {e}", req_id=req_id)


def can_start_oven(oven: Dict[str, Any], all_ovens: List[Dict[str, Any]]) -> bool:
    """Check if oven can start based on is_blocking dependencies."""
    task_order = oven.get("task_order")
    recipe_id = oven.get("recipe_id")
    
    if task_order == 1:
        log("can_start_oven", "First task, can start", oven_id=oven.get("id"))
        return True
    
    for prev_oven in all_ovens:
        if prev_oven.get("recipe_id") != recipe_id:
            continue
        
        prev_order = prev_oven.get("task_order")
        if prev_order >= task_order:
            continue
        
        if prev_oven.get("is_blocking") and prev_oven.get("processing_status") != "complete":
            log("can_start_oven", "Blocked by previous task", 
                oven_id=oven.get("id"), blocked_by_order=prev_order)
            return False
    
    log("can_start_oven", "Dependencies met, can start", oven_id=oven.get("id"))
    return True


def start_oven(oven: Dict[str, Any]):
    """Start a StackStorm execution for this oven."""
    oven_id = oven.get("id")
    ingredient_id = oven.get("ingredient_id")
    
    try:
        response = requests.get(
            f"{POUNDCAKE_API_URL}/api/v1/ingredients/{ingredient_id}",
            timeout=10
        )
        response.raise_for_status()
        ingredient = response.json()
        
        task_name = ingredient.get("task_name")
        log("start_oven", "Retrieved ingredient", 
            oven_id=oven_id, task_name=task_name, st2_action=ingredient.get("st2_action"))
        
        st2_payload = {
            "action": ingredient.get("st2_action"),
            "parameters": ingredient.get("parameters", {})
        }
        
        alert_id = oven.get("alert_id")
        if alert_id:
            response = requests.get(
                f"{POUNDCAKE_API_URL}/api/v1/alerts/{alert_id}",
                timeout=10
            )
            if response.status_code == 200:
                alert = response.json()
                st2_payload["parameters"]["alert"] = {
                    "fingerprint": alert.get("fingerprint"),
                    "name": alert.get("alert_name"),
                    "severity": alert.get("severity"),
                    "instance": alert.get("instance"),
                    "labels": alert.get("labels", {})
                }
                log("start_oven", "Added alert context to parameters", oven_id=oven_id)
        
        headers = {"Content-Type": "application/json"}
        if ST2_API_KEY:
            headers["St2-Api-Key"] = ST2_API_KEY
        
        log("start_oven", "Calling StackStorm API", oven_id=oven_id, action=st2_payload["action"])
        
        response = requests.post(
            f"{ST2_API_URL}/executions",
            json=st2_payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 401:
            log("start_oven", "ERROR: ST2 authentication required", oven_id=oven_id)
            return
        
        response.raise_for_status()
        execution = response.json()
        execution_id = execution.get("id")
        
        update_data = {
            "processing_status": "processing",
            "action_id": execution_id,
            "started_at": datetime.utcnow().isoformat()
        }
        
        response = requests.put(
            f"{POUNDCAKE_API_URL}/api/v1/ovens/{oven_id}",
            json=update_data,
            timeout=10
        )
        response.raise_for_status()
        
        log("start_oven", f"✅ Started successfully", 
            oven_id=oven_id, task_name=task_name, action_id=execution_id)
    except Exception as e:
        log("start_oven", f"ERROR: {e}", oven_id=oven_id)


if __name__ == "__main__":
    oven_loop()
