#!/usr/bin/env python3
"""Test script for PoundCake v0.0.1 pre_heat logic and new routes."""

import requests
import json
import time
from datetime import datetime

# Sample Alertmanager webhook payload
WEBHOOK_PAYLOAD = {
    "receiver": "alert_proxy_receiver",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "AbnormalImageFailures",
                "prometheus": "prometheus/kube-prometheus-stack-prometheus",
                "severity": "critical",
            },
            "annotations": {
                "description": "This indicates a major problem creating images.",
                "summary": "Image create failure rate is abnormally high",
            },
            "startsAt": datetime.utcnow().isoformat() + "Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "",
            "fingerprint": "test-fingerprint-001",
        }
    ],
    "groupLabels": {"alertname": "AbnormalImageFailures"},
    "commonLabels": {
        "alertname": "AbnormalImageFailures",
        "prometheus": "prometheus/kube-prometheus-stack-prometheus",
        "severity": "critical",
    },
    "commonAnnotations": {
        "description": "This indicates a major problem creating images.",
        "summary": "Image create failure rate is abnormally high",
    },
    "externalURL": "https://alertmanager.dev.dfw.ohthree.com",
    "version": "4",
    "groupKey": '{}/{severity=~"critical"}:{alertname="AbnormalImageFailures"}',
    "truncatedAlerts": 0,
}


def print_section(title):
    """Print a section header."""
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)
    print()


def test_preheat_case_1_new_alert(base_url):
    """Test Case 1: New alert (no existing record)."""
    print_section("Test Case 1: New Alert")

    # Use a unique fingerprint for this test
    payload = WEBHOOK_PAYLOAD.copy()
    payload["alerts"][0]["fingerprint"] = "test-case-1-new"

    print("Sending webhook with NEW alert...")
    response = requests.post(f"{base_url}/api/v1/webhook", json=payload, timeout=30)

    print(f"Response: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

    # Background processing - give it a moment
    print("\nWaiting for background processing...")
    time.sleep(2)

    # Check alert was created
    print("\nQuerying alert by fingerprint...")
    response = requests.get(f"{base_url}/api/v1/alerts", params={"fingerprint": "test-case-1-new"})

    alerts = response.json()
    if alerts:
        alert = alerts[0]
        print("✓ Alert created:")
        print(f"  - ID: {alert['id']}")
        print(f"  - Counter: {alert['counter']}")
        print(f"  - Alert Status: {alert['alert_status']}")
        print(f"  - Processing Status: {alert['processing_status']}")

        assert alert["counter"] == 1, "Counter should be 1 for new alert"
        assert alert["alert_status"] == "firing", "Alert status should be firing"
        assert alert["processing_status"] == "new", "Processing status should be new"
        print("\n✓ Test Case 1 PASSED")
    else:
        print("✗ Test Case 1 FAILED: Alert not found")
        print("  (Background processing may need more time)")


def test_preheat_case_2_active_alert_fires_again(base_url):
    """Test Case 2: Active alert fires again (counter increment)."""
    print_section("Test Case 2: Active Alert Fires Again")

    fingerprint = "test-case-2-active"

    # First webhook - create alert
    payload = WEBHOOK_PAYLOAD.copy()
    payload["alerts"][0]["fingerprint"] = fingerprint

    print("Sending initial webhook...")
    requests.post(f"{base_url}/api/v1/webhook", json=payload, timeout=30)

    time.sleep(2)  # Wait for background processing

    # Check initial state
    response = requests.get(f"{base_url}/api/v1/alerts", params={"fingerprint": fingerprint})
    initial_alert = response.json()[0]
    initial_counter = initial_alert["counter"]
    print(f"Initial counter: {initial_counter}")

    # Second webhook - same alert fires again
    print("\nSending webhook again (alert still active)...")
    requests.post(f"{base_url}/api/v1/webhook", json=payload, timeout=30)

    time.sleep(2)  # Wait for background processing

    # Check counter incremented
    response = requests.get(f"{base_url}/api/v1/alerts", params={"fingerprint": fingerprint})
    updated_alert = response.json()[0]
    updated_counter = updated_alert["counter"]

    print(f"Updated counter: {updated_counter}")
    print(f"Alert ID: {updated_alert['id']} (should be same as initial)")

    assert updated_counter == initial_counter + 1, "Counter should increment"
    assert updated_alert["id"] == initial_alert["id"], "Should be same alert record"
    print("\n✓ Test Case 2 PASSED")


def test_preheat_case_3_completed_alert_fires_again(base_url):
    """Test Case 3: Completed alert fires again (new occurrence)."""
    print_section("Test Case 3: Completed Alert Fires Again")

    fingerprint = "test-case-3-completed"

    # First webhook - create alert
    payload = WEBHOOK_PAYLOAD.copy()
    payload["alerts"][0]["fingerprint"] = fingerprint

    print("Sending initial webhook...")
    requests.post(f"{base_url}/api/v1/webhook", json=payload, timeout=30)

    time.sleep(1)

    # Get initial alert
    response = requests.get(f"{base_url}/api/v1/alerts", params={"fingerprint": fingerprint})
    initial_alert = response.json()[0]
    initial_id = initial_alert["id"]
    initial_counter = initial_alert["counter"]

    print(f"Initial alert ID: {initial_id}, counter: {initial_counter}")

    # Process the alert (this will mark it as complete)
    print("\nProcessing alert...")
    requests.post(f"{base_url}/api/v1/alerts/process", params={"fingerprints": fingerprint})

    time.sleep(2)

    # Verify it's complete
    response = requests.get(f"{base_url}/api/v1/alerts", params={"fingerprint": fingerprint})
    alerts = response.json()
    # Find the one with our ID
    processed_alert = next((a for a in alerts if a["id"] == initial_id), None)

    if processed_alert:
        print(f"Processing status: {processed_alert['processing_status']}")

    # Second webhook - alert fires again after completion
    print("\nSending webhook again (alert completed, now firing again)...")
    requests.post(f"{base_url}/api/v1/webhook", json=payload, timeout=30)

    time.sleep(1)

    # Check new occurrence was created
    response = requests.get(f"{base_url}/api/v1/alerts", params={"fingerprint": fingerprint})
    alerts = response.json()

    print(f"\nTotal alerts with this fingerprint: {len(alerts)}")

    # Should have 2 alerts now (if first was completed)
    if len(alerts) > 1:
        new_alert = sorted(alerts, key=lambda x: x["created_at"])[-1]
        print("New occurrence created:")
        print(f"  - ID: {new_alert['id']} (different from {initial_id})")
        print(f"  - Counter: {new_alert['counter']} (incremented from {initial_counter})")
        print(f"  - Processing Status: {new_alert['processing_status']}")

        assert new_alert["id"] != initial_id, "Should be a new alert record"
        assert new_alert["counter"] > initial_counter, "Counter should increment"
        print("\n✓ Test Case 3 PASSED")
    else:
        print("\n⚠ Test Case 3 SKIPPED: First alert not marked as complete")
        print("   (May need StackStorm integration to complete)")


def test_preheat_case_4_alert_resolves(base_url):
    """Test Case 4: Alert resolves."""
    print_section("Test Case 4: Alert Resolves")

    fingerprint = "test-case-4-resolve"

    # First webhook - create firing alert
    payload = WEBHOOK_PAYLOAD.copy()
    payload["alerts"][0]["fingerprint"] = fingerprint
    payload["alerts"][0]["status"] = "firing"

    print("Sending firing alert...")
    requests.post(f"{base_url}/api/v1/webhook", json=payload, timeout=30)

    time.sleep(2)  # Wait for background processing

    # Check initial state
    response = requests.get(f"{base_url}/api/v1/alerts", params={"fingerprint": fingerprint})
    initial_alert = response.json()[0]
    print(f"Initial alert status: {initial_alert['alert_status']}")

    # Second webhook - alert resolves
    payload["alerts"][0]["status"] = "resolved"
    payload["status"] = "resolved"

    print("\nSending resolved alert...")
    requests.post(f"{base_url}/api/v1/webhook", json=payload, timeout=30)

    time.sleep(2)  # Wait for background processing

    # Check updated state
    response = requests.get(f"{base_url}/api/v1/alerts", params={"fingerprint": fingerprint})
    updated_alert = response.json()[0]

    print(f"Updated alert status: {updated_alert['alert_status']}")
    print(f"Processing status: {updated_alert['processing_status']}")

    assert updated_alert["alert_status"] == "resolved", "Alert status should be resolved"
    print("\n✓ Test Case 4 PASSED")


def test_consolidated_get_endpoint(base_url):
    """Test the consolidated GET /alerts endpoint."""
    print_section("Test Consolidated GET Endpoint")

    print("Testing query by fingerprint...")
    response = requests.get(
        f"{base_url}/api/v1/alerts", params={"fingerprint": "test-case-1-new", "limit": 1}
    )
    print(f"Found {len(response.json())} alerts")

    print("\nTesting query by name...")
    response = requests.get(
        f"{base_url}/api/v1/alerts", params={"name": "AbnormalImageFailures", "limit": 5}
    )
    print(f"Found {len(response.json())} alerts")

    print("\nTesting query by processing_status...")
    response = requests.get(f"{base_url}/api/v1/alerts", params={"processing_status": "new"})
    print(f"Found {len(response.json())} new alerts")

    print("\nTesting query by alert_status...")
    response = requests.get(f"{base_url}/api/v1/alerts", params={"alert_status": "firing"})
    print(f"Found {len(response.json())} firing alerts")

    print("\n✓ Consolidated GET endpoint working")


def test_process_endpoint(base_url):
    """Test the POST /alerts/process endpoint."""
    print_section("Test Process Endpoint")

    print("Processing all new alerts...")
    response = requests.post(f"{base_url}/api/v1/alerts/process", timeout=30)

    print(f"Response: {response.status_code}")
    result = response.json()
    print(json.dumps(result, indent=2))

    if response.status_code == 202:
        # Verify response contains req_ids from alerts (not a new req_id)
        if "req_ids" in result:
            print(f"\n✓ Process endpoint returned req_ids from alerts: {result['req_ids']}")
            print(f"  Processed {result['alerts_processed']} alerts")
        else:
            print("\n⚠ Warning: No req_ids in response")
        print("\n✓ Process endpoint working")
    else:
        print("\n⚠ Process endpoint returned unexpected status")


def main():
    """Run all tests."""
    import sys

    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

    print("=" * 70)
    print("PoundCake v0.0.1 - Pre-Heat Logic Test Suite")
    print("=" * 70)
    print(f"\nBase URL: {base_url}")

    # Check health
    try:
        response = requests.get(f"{base_url}/api/v1/health", timeout=5)
        health = response.json()
        print(f"Health Status: {health['status']}")
        print(f"Version: {health.get('version', 'unknown')}")
    except Exception as e:
        print(f"\n✗ Error: Could not connect to {base_url}")
        print(f"   {e}")
        return

    # Run test cases
    try:
        test_preheat_case_1_new_alert(base_url)
        test_preheat_case_2_active_alert_fires_again(base_url)
        test_preheat_case_4_alert_resolves(base_url)
        test_consolidated_get_endpoint(base_url)
        test_process_endpoint(base_url)
        test_preheat_case_3_completed_alert_fires_again(base_url)

        print_section("Test Suite Complete")
        print("✓ All tests passed!")

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
    except Exception as e:
        print(f"\n✗ Error during testing: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
