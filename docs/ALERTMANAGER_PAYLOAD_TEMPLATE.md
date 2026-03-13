# Alertmanager Payload Template

PoundCake expects a provider-neutral Alertmanager payload. Alert rules should supply descriptive alert data only. Provider-specific routing belongs in the communications route configuration, not in alert labels or annotations.

## Required fields

Top level:

- `status`
- `alerts`

For each alert in `alerts`:

- `status`
- `fingerprint`
- `startsAt`
- `labels.alertname`
- `labels.group_name`
- `labels.severity`
- `annotations.summary`
- `annotations.description`

## Standard optional fields

Top level:

- `receiver`
- `groupKey`
- `groupLabels`
- `commonLabels`
- `commonAnnotations`
- `externalURL`
- `version`
- `truncatedAlerts`

Labels:

- `instance`
- `service`
- `team`
- `environment`
- `cluster`
- `namespace`
- `job`
- `region`

Annotations:

- `runbook_url`
- `dashboard_url`
- `playbook_url`
- `investigation_url`
- `silence_url`
- `customer_impact`
- `suggested_action`

Alert field:

- `generatorURL`

## Example payload

```json
{
  "status": "firing",
  "receiver": "webhook",
  "alerts": [
    {
      "status": "firing",
      "fingerprint": "hello-world-test-12345",
      "startsAt": "2026-01-09T21:00:00Z",
      "labels": {
        "alertname": "HelloWorldAlert",
        "group_name": "hello-world-workflow",
        "severity": "warning",
        "instance": "test-server:8080",
        "service": "demo-api",
        "team": "platform",
        "environment": "test"
      },
      "annotations": {
        "summary": "Hello World Test Alert",
        "description": "This is a test alert to verify the webhook contract.",
        "runbook_url": "https://docs.example.com/runbooks/hello-world",
        "dashboard_url": "https://grafana.example/d/hello-world",
        "suggested_action": "Check the service and follow the runbook if remediation is needed."
      },
      "generatorURL": "https://prometheus.example/graph?g0.expr=up"
    }
  ]
}
```

## Example rule annotations

```yaml
labels:
  severity: warning
  group_name: hello-world-workflow
annotations:
  summary: Hello World Test Alert
  description: This is a test alert to verify the webhook contract.
  runbook_url: https://docs.example.com/runbooks/hello-world
  dashboard_url: https://grafana.example/d/hello-world
  suggested_action: Check the service and follow the runbook if remediation is needed.
```

## Rendering notes

- PoundCake turns URLs into provider-native links where the provider supports them.
- Rackspace Core BBCode is generated in the mixer and is always enabled internally.
- Discord, GitHub, Jira, ServiceNow, PagerDuty, and Teams are rendered from the same canonical alert envelope using provider-native output formats.
