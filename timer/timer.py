#!/usr/bin/env python3
#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Timer Service - Monitors oven executions and updates completion status."""

import os
import time
import requests
from datetime import datetime
from typing import List, Dict, Any

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000")
TIMER_INTERVAL = int(os.getenv("TIMER_INTERVAL", "10"))
ST2_API_URL = os.getenv("ST2_API_URL", "http://st2api:9101/v1")
ST2_API_KEY = os.getenv("ST2_API_KEY", "")


def log(function: str, message: str, **kwargs):
    """Structured logging with function name."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
    extra_str = f" [{extra}]" if extra else ""
    print(f"[{timestamp}] timer.{function}: {message}{extra_str}", flush=True)


def timer_loop():
    """Main timer loop - runs continuously on schedule."""
    log("timer_loop", f"Timer service started", interval=f"{TIMER_INTERVAL}s")
    log("timer_loop", f"Configuration", api=POUNDCAKE_API_URL, st2=ST2_API_URL)
    
    while True:
        try:
            log("timer_loop", "=== Cycle started ===")
            process_executing_ovens()
            check_sla_violations()
            update_alert_statuses()
            log("timer_loop", "=== Cycle complete ===\n")
        except Exception as e:
            log("timer_loop", f"ERROR: {e}")
            import traceback
            traceback.print_exc()
        
        time.sleep(TIMER_INTERVAL)


def process_executing_ovens():
    """Find ovens with processing_status='processing' and check their status."""
    try:
        response = requests.get(
            f"{POUNDCAKE_API_URL}/api/v1/ovens",
            params={"processing_status": "processing"},
            timeout=10
        )
        response.raise_for_status()
        ovens = response.json()
        
        if not ovens:
            log("process_executing_ovens", "No ovens in processing state")
            return
        
        log("process_executing_ovens", f"Found ovens to check", count=len(ovens))
        
        for oven in ovens:
            check_oven_execution(oven)
    except Exception as e:
        log("process_executing_ovens", f"ERROR: {e}")


def check_oven_execution(oven: Dict[str, Any]):
    """Check a single oven's StackStorm execution status."""
    action_id = oven.get("action_id")
    oven_id = oven.get("id")
    
    if not action_id:
        log("check_oven_execution", "Missing action_id, skipping", oven_id=oven_id)
        return
    
    try:
        headers = {}
        if ST2_API_KEY:
            headers["St2-Api-Key"] = ST2_API_KEY
        
        response = requests.get(
            f"{ST2_API_URL}/executions/{action_id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 404:
            log("check_oven_execution", "Execution not found in ST2", 
                oven_id=oven_id, action_id=action_id)
            return
        
        if response.status_code == 401:
            log("check_oven_execution", "ST2 authentication required", oven_id=oven_id)
            return
        
        response.raise_for_status()
        execution = response.json()
        st2_status = execution.get("status")
        
        if st2_status in ["succeeded", "failed", "timeout", "canceled"]:
            update_oven_completion(oven, execution)
        else:
            log("check_oven_execution", "Still running", 
                oven_id=oven_id, action_id=action_id, st2_status=st2_status)
    except Exception as e:
        log("check_oven_execution", f"ERROR: {e}", oven_id=oven_id, action_id=action_id)


def update_oven_completion(oven: Dict[str, Any], execution: Dict[str, Any]):
    """Update oven with completion results."""
    oven_id = oven.get("id")
    
    try:
        started_at_str = oven.get("started_at")
        if started_at_str:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            completed_at = datetime.utcnow()
            actual_duration = int((completed_at - started_at).total_seconds())
        else:
            actual_duration = 0
            completed_at = datetime.utcnow()
        
        update_data = {
            "processing_status": "complete",
            "st2_status": execution.get("status"),
            "action_result": execution.get("result"),
            "completed_at": completed_at.isoformat(),
            "actual_duration": actual_duration
        }
        
        if execution.get("status") != "succeeded":
            result = execution.get("result", {})
            if isinstance(result, dict):
                update_data["error_message"] = result.get("stderr", str(result))
            else:
                update_data["error_message"] = str(result)
        
        response = requests.put(
            f"{POUNDCAKE_API_URL}/api/v1/ovens/{oven_id}",
            json=update_data,
            timeout=10
        )
        response.raise_for_status()
        
        expected = oven.get("expected_duration", 0)
        status_icon = "✅" if actual_duration <= expected else "⚠️"
        log("update_oven_completion", f"{status_icon} Completed", 
            oven_id=oven_id, actual=f"{actual_duration}s", expected=f"{expected}s",
            st2_status=execution.get("status"))
    except Exception as e:
        log("update_oven_completion", f"ERROR: {e}", oven_id=oven_id)


def check_sla_violations():
    """Check for executions that exceeded expected time_to_complete."""
    try:
        response = requests.get(
            f"{POUNDCAKE_API_URL}/api/v1/alerts",
            params={"processing_status": "processing"},
            timeout=10
        )
        response.raise_for_status()
        alerts = response.json()
        
        if not alerts:
            return
        
        for alert in alerts:
            check_alert_sla(alert)
    except Exception as e:
        log("check_sla_violations", f"ERROR: {e}")


def check_alert_sla(alert: Dict[str, Any]):
    """Check if alert's recipe execution exceeded expected time."""
    req_id = alert.get("req_id")
    
    try:
        response = requests.get(
            f"{POUNDCAKE_API_URL}/api/v1/executions/{req_id}",
            timeout=10
        )
        response.raise_for_status()
        executions = response.json()
        
        if not executions:
            return
        
        total_expected = sum(e.get("expected_duration", 0) for e in executions)
        completed = [e for e in executions if e.get("processing_status") == "complete"]
        total_actual = sum(e.get("actual_duration", 0) for e in completed)
        
        if len(completed) == len(executions) and total_actual > total_expected:
            violation = total_actual - total_expected
            log("check_alert_sla", "⚠️ SLA VIOLATION", 
                req_id=req_id, violation=f"{violation}s", 
                expected=f"{total_expected}s", actual=f"{total_actual}s")
    except Exception as e:
        log("check_alert_sla", f"ERROR: {e}", req_id=req_id)


def update_alert_statuses():
    """Update alerts to 'complete' when all ovens are done."""
    try:
        response = requests.get(
            f"{POUNDCAKE_API_URL}/api/v1/alerts",
            params={"processing_status": "processing"},
            timeout=10
        )
        response.raise_for_status()
        alerts = response.json()
        
        if not alerts:
            return
        
        log("update_alert_statuses", "Checking alerts for completion", count=len(alerts))
        
        for alert in alerts:
            check_alert_completion(alert)
    except Exception as e:
        log("update_alert_statuses", f"ERROR: {e}")


def check_alert_completion(alert: Dict[str, Any]):
    """Check if all ovens for an alert are complete."""
    req_id = alert.get("req_id")
    alert_id = alert.get("id")
    
    try:
        response = requests.get(
            f"{POUNDCAKE_API_URL}/api/v1/executions/{req_id}",
            timeout=10
        )
        response.raise_for_status()
        executions = response.json()
        
        if not executions:
            return
        
        all_complete = all(e.get("processing_status") == "complete" for e in executions)
        
        if all_complete:
            response = requests.put(
                f"{POUNDCAKE_API_URL}/api/v1/alerts/{alert_id}",
                json={"processing_status": "complete"},
                timeout=10
            )
            response.raise_for_status()
            
            success = sum(1 for e in executions if e.get("st2_status") == "succeeded")
            total = len(executions)
            
            log("check_alert_completion", "✅ Alert complete", 
                alert_id=alert_id, success=success, total=total, req_id=req_id)
    except Exception as e:
        log("check_alert_completion", f"ERROR: {e}", alert_id=alert_id, req_id=req_id)


if __name__ == "__main__":
    timer_loop()
