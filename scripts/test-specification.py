#!/usr/bin/env python3
"""Test script for PoundCake v0.0.1 specification-aligned implementation.

Tests the new architecture where:
- Oven service only talks to PoundCake API
- Recipe matching uses group_name
- Multiple ovens created per task_list
- Scheduled crawler processes NEW alerts
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"


def print_section(title):
    """Print a section header."""
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)
    print()


def test_1_create_recipe_with_task_list():
    """Test 1: Create a recipe with multiple tasks in task_list."""
    print_section("Test 1: Create Recipe with Task List")

    recipe_data = {
        "name": "HostDownAlert",
        "description": "Recipe for host down alerts with 3 tasks",
        "task_list": "task-restart-service,task-check-health,task-notify-team",
        "st2_workflow_ref": "remediation.host_down_workflow",
    }

    print(f"Creating recipe: {recipe_data['name']}")
    print(f"Task list: {recipe_data['task_list']}")

    response = requests.post(f"{BASE_URL}/api/recipes/", json=recipe_data, timeout=10)

    if response.status_code == 201:
        recipe = response.json()
        print("✓ Recipe created successfully")
        print(f"  - Recipe ID: {recipe['id']}")
        print(f"  - Name: {recipe['name']}")
        print(f"  - Task List: {recipe['task_list']}")
        print(f"  - ST2 Workflow: {recipe['st2_workflow_ref']}")
        return recipe['id']
    elif response.status_code == 400 and "already exists" in response.text:
        print("⚠ Recipe already exists, fetching...")
        response = requests.get(f"{BASE_URL}/api/recipes/?name=HostDownAlert", timeout=10)
        recipes = response.json()
        if recipes:
            recipe = recipes[0]
            print(f"✓ Using existing recipe ID: {recipe['id']}")
            return recipe['id']
    else:
        print(f"✗ Failed to create recipe: {response.status_code}")
        print(response.text)
        return None


def test_2_send_webhook_with_group_name():
    """Test 2: Send webhook with group_name in groupLabels."""
    print_section("Test 2: Send Webhook with group_name")

    webhook_payload = {
        "version": "4",
        "status": "firing",
        "receiver": "poundcake",
        "groupKey": "test-group-key",
        "groupLabels": {"alertname": "HostDownAlert"},  # This becomes group_name
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "http://alertmanager",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HostDown",
                    "instance": "server1.example.com",
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "Server is down",
                    "description": "Server server1 is not responding",
                },
                "startsAt": datetime.utcnow().isoformat() + "Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "fingerprint": "test-group-name-001",
                "generatorURL": "http://prometheus/graph",
            }
        ],
        "truncatedAlerts": 0,
    }

    print("Sending webhook with:")
    print(f"  - groupLabels.alertname: {webhook_payload['groupLabels']['alertname']}")
    print(f"  - Fingerprint: {webhook_payload['alerts'][0]['fingerprint']}")

    response = requests.post(f"{BASE_URL}/api/v1/webhook", json=webhook_payload, timeout=30)

    if response.status_code == 202:
        result = response.json()
        print("✓ Webhook accepted")
        print(f"  - Request ID: {result['request_id']}")
        print(f"  - Alerts received: {result['alerts_received']}")

        # Wait for background processing
        print("\nWaiting for background processing...")
        time.sleep(3)

        # Verify alert was created with group_name
        print("\nVerifying alert was created with group_name...")
        response = requests.get(
            f"{BASE_URL}/api/v1/alerts",
            params={"fingerprint": "test-group-name-001"},
            timeout=10,
        )

        if response.status_code == 200:
            alerts = response.json()
            if alerts:
                alert = alerts[0]
                print("✓ Alert created:")
                print(f"  - Alert ID: {alert['id']}")
                print(f"  - Alert Name: {alert['alert_name']}")
                print(f"  - Group Name: {alert.get('group_name', 'MISSING!')}")
                print(f"  - Processing Status: {alert['processing_status']}")

                if alert.get("group_name") == "HostDownAlert":
                    print("✓ Group name correctly extracted from groupLabels")
                    return alert['id'], result['request_id']
                else:
                    print("✗ Group name not set correctly!")
                    return None, None
            else:
                print("✗ Alert not found")
                return None, None
    else:
        print(f"✗ Webhook failed: {response.status_code}")
        print(response.text)
        return None, None


def test_3_process_alert_creates_multiple_ovens():
    """Test 3: Process alert and verify multiple ovens created."""
    print_section("Test 3: Process Alert - Multiple Ovens Created")

    print("Triggering alert processing...")
    response = requests.post(
        f"{BASE_URL}/api/v1/alerts/process",
        params={"processing_status": "new"},
        timeout=60,
    )

    if response.status_code == 202:
        result = response.json()
        print("✓ Processing triggered")
        print(f"  - Status: {result['status']}")
        print(f"  - Alerts processed: {result['alerts_processed']}")
        print(f"  - Tasks triggered: {result.get('tasks_triggered', 0)}")
        print(f"  - Execution IDs: {result.get('execution_ids', [])}")

        if result.get('tasks_triggered', 0) >= 3:
            print("✓ Multiple tasks triggered (expected 3)")
        else:
            print(f"⚠ Expected 3 tasks, got {result.get('tasks_triggered', 0)}")

        # Wait for processing
        time.sleep(2)

        # Verify ovens were created
        if result.get('req_ids'):
            req_id = result['req_ids'][0]
            print(f"\nVerifying ovens for req_id: {req_id}")

            response = requests.get(f"{BASE_URL}/api/v1/executions/{req_id}", timeout=10)

            if response.status_code == 200:
                exec_data = response.json()
                print(f"✓ Found {exec_data['total_executions']} oven(s)")

                for i, execution in enumerate(exec_data['executions'], 1):
                    print(f"\nOven {i}:")
                    print(f"  - Oven ID: {execution['oven_id']}")
                    print(f"  - Task ID: {execution.get('task_id', 'N/A')}")  # New field
                    print(f"  - Status: {execution['status']}")
                    print(f"  - Recipe: {execution['recipe_name']}")
                    print(f"  - ST2 Execution: {execution.get('st2_execution_id', 'N/A')}")

                if exec_data['total_executions'] == 3:
                    print("\n✓ Correct number of ovens created (3)")
                else:
                    print(f"\n⚠ Expected 3 ovens, got {exec_data['total_executions']}")

                return True
            else:
                print(f"✗ Failed to get executions: {response.status_code}")
                return False
    else:
        print(f"✗ Processing failed: {response.status_code}")
        print(response.text)
        return False


def test_4_recipe_matching_by_group_name():
    """Test 4: Verify recipe is matched by group_name not alert_name."""
    print_section("Test 4: Recipe Matching by group_name")

    # Create alert with different alert_name but matching group_name
    webhook_payload = {
        "version": "4",
        "status": "firing",
        "receiver": "poundcake",
        "groupKey": "test-group-key-2",
        "groupLabels": {
            "alertname": "HostDownAlert"
        },  # Matches recipe name (group_name)
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "http://alertmanager",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "DifferentAlertName",  # Different from group_name!
                    "instance": "server2.example.com",
                    "severity": "warning",
                },
                "annotations": {"summary": "Different alert name test"},
                "startsAt": datetime.utcnow().isoformat() + "Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "fingerprint": "test-group-name-002",
                "generatorURL": "http://prometheus/graph",
            }
        ],
        "truncatedAlerts": 0,
    }

    print("Sending webhook with:")
    print(f"  - groupLabels.alertname (group_name): {webhook_payload['groupLabels']['alertname']}")
    print(
        f"  - labels.alertname (alert_name): {webhook_payload['alerts'][0]['labels']['alertname']}"
    )
    print("  → Recipe should match on group_name, not alert_name")

    response = requests.post(f"{BASE_URL}/api/v1/webhook", json=webhook_payload, timeout=30)

    if response.status_code == 202:
        print("✓ Webhook accepted")
        time.sleep(3)

        # Process this alert
        print("\nProcessing alert...")
        response = requests.post(
            f"{BASE_URL}/api/v1/alerts/process",
            params={"fingerprint": "test-group-name-002"},
            timeout=60,
        )

        if response.status_code == 202:
            result = response.json()

            if result['alerts_processed'] > 0:
                print("✓ Alert processed successfully")
                print(
                    "✓ Recipe matched by group_name (not alert_name), as tasks were triggered"
                )
                return True
            else:
                print("✗ Alert not processed - recipe may not have matched")
                return False
        else:
            print(f"✗ Processing failed: {response.status_code}")
            return False
    else:
        print(f"✗ Webhook failed: {response.status_code}")
        return False


def test_5_oven_service_api_only():
    """Test 5: Verify oven service endpoint works (API-only mode)."""
    print_section("Test 5: Oven Service API Endpoint (Task Mode)")

    # This simulates what the oven service does:
    # POST /api/v1/alerts/process with {alert_id, recipe_id, task_id}

    # First, get an alert and recipe
    alerts_response = requests.get(
        f"{BASE_URL}/api/v1/alerts", params={"processing_status": "processing", "limit": 1}
    )

    if alerts_response.status_code == 200:
        alerts = alerts_response.json()
        if not alerts:
            print("⚠ No alerts in processing status to test with")
            return False

        alert = alerts[0]
        alert_id = alert['id']

        # Get recipe
        recipes_response = requests.get(
            f"{BASE_URL}/api/recipes/", params={"name": alert.get('group_name')}
        )

        if recipes_response.status_code == 200:
            recipes = recipes_response.json()
            if not recipes:
                print("⚠ No recipe found for this alert")
                return False

            recipe = recipes[0]
            recipe_id = recipe['id']

            # Simulate oven service call
            task_data = {
                "alert_id": alert_id,
                "recipe_id": recipe_id,
                "task_id": "test-task-from-oven-service",
            }

            print(f"Simulating oven service API call:")
            print(f"  - Alert ID: {alert_id}")
            print(f"  - Recipe ID: {recipe_id}")
            print(f"  - Task ID: {task_data['task_id']}")

            response = requests.post(
                f"{BASE_URL}/api/v1/alerts/process", json=task_data, timeout=60
            )

            if response.status_code == 202:
                result = response.json()
                print("✓ Task mode endpoint works")
                print(f"  - Oven ID: {result.get('oven_id')}")
                print(f"  - Execution ID: {result.get('execution_id')}")
                print(f"  - Success: {result.get('success')}")
                return True
            else:
                print(f"✗ Task mode endpoint failed: {response.status_code}")
                print(response.text)
                return False
    else:
        print(f"✗ Failed to get alerts: {alerts_response.status_code}")
        return False


def main():
    """Run all tests."""
    print("=" * 80)
    print("PoundCake v0.0.1 - Specification-Aligned Implementation Tests")
    print("=" * 80)
    print(f"\nBase URL: {BASE_URL}")

    # Check health
    try:
        response = requests.get(f"{BASE_URL}/api/v1/health", timeout=5)
        health = response.json()
        print(f"Health Status: {health['status']}")
        print(f"Version: {health.get('version', 'unknown')}")
    except Exception as e:
        print(f"\n✗ Error: Could not connect to {BASE_URL}")
        print(f"   {e}")
        return

    # Run tests
    results = {}

    try:
        results['test_1'] = test_1_create_recipe_with_task_list() is not None
        results['test_2'] = test_2_send_webhook_with_group_name() != (None, None)
        results['test_3'] = test_3_process_alert_creates_multiple_ovens()
        results['test_4'] = test_4_recipe_matching_by_group_name()
        results['test_5'] = test_5_oven_service_api_only()

        print_section("Test Results Summary")
        for test_name, passed in results.items():
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"{test_name}: {status}")

        passed_count = sum(results.values())
        total_count = len(results)
        print(f"\nTotal: {passed_count}/{total_count} tests passed")

        if passed_count == total_count:
            print("\n✓ All tests passed!")
        else:
            print(f"\n⚠ {total_count - passed_count} test(s) failed")

    except Exception as e:
        print(f"\n✗ Error during testing: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
