from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services import bakery_collectors


def _node(
    name: str,
    *,
    ready: bool,
    zone: str,
    unschedulable: bool = False,
):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            labels={
                "node-role.kubernetes.io/worker": "",
                "topology.kubernetes.io/zone": zone,
            },
            annotations={"cluster-autoscaler.kubernetes.io/safe-to-evict": "true"},
        ),
        spec=SimpleNamespace(
            unschedulable=unschedulable,
            taints=[SimpleNamespace(key="dedicated", value="infra", effect="NoSchedule")],
        ),
        status=SimpleNamespace(
            capacity={
                "cpu": "4",
                "memory": "16Gi",
                "ephemeral-storage": "100Gi",
                "pods": "110",
            },
            allocatable={
                "cpu": "3800m",
                "memory": "14Gi",
                "ephemeral-storage": "90Gi",
                "pods": "100",
            },
            conditions=[
                SimpleNamespace(
                    type="Ready",
                    status="True" if ready else "False",
                    reason="KubeletReady" if ready else "KubeletNotReady",
                    message="node healthy" if ready else "node unreachable",
                    last_transition_time=None,
                    last_heartbeat_time=None,
                )
            ],
            addresses=[SimpleNamespace(type="InternalIP", address="192.168.0.10")],
            node_info=SimpleNamespace(
                kubelet_version="v1.31.0",
                container_runtime_version="containerd://2.0.0",
                operating_system="linux",
                os_image="Ubuntu 24.04",
                architecture="amd64",
                kernel_version="6.8.0",
            ),
        ),
    )


class _FakeCoreV1:
    def list_node(self):
        return SimpleNamespace(
            items=[
                _node("worker-1", ready=True, zone="ord-a"),
                _node("worker-2", ready=False, zone="ord-b", unschedulable=True),
            ]
        )

    def list_persistent_volume(self):
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    metadata=SimpleNamespace(name="pv-fast-1", labels={}, annotations={}),
                    spec=SimpleNamespace(
                        storage_class_name="fast",
                        capacity={"storage": "100Gi"},
                        access_modes=["ReadWriteOnce"],
                        persistent_volume_reclaim_policy="Delete",
                        claim_ref=SimpleNamespace(namespace="rackspace", name="data-api-0"),
                        volume_mode="Filesystem",
                        csi=SimpleNamespace(driver="csi.example"),
                    ),
                    status=SimpleNamespace(phase="Bound"),
                )
            ]
        )

    def list_namespaced_persistent_volume_claim(self, namespace: str, limit: int):
        assert namespace == "rackspace"
        assert limit == 25
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    metadata=SimpleNamespace(
                        name="data-api-0", namespace=namespace, labels={}, annotations={}
                    ),
                    spec=SimpleNamespace(
                        storage_class_name="fast",
                        resources=SimpleNamespace(requests={"storage": "100Gi"}),
                        access_modes=["ReadWriteOnce"],
                        volume_name="pv-fast-1",
                        volume_mode="Filesystem",
                    ),
                    status=SimpleNamespace(phase="Bound"),
                )
            ]
        )

    def list_namespaced_pod(self, namespace: str, limit: int):
        assert namespace == "rackspace"
        assert limit == 25
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    metadata=SimpleNamespace(name="api-5d9f", labels={"app": "api"}),
                    spec=SimpleNamespace(node_name="worker-1"),
                    status=SimpleNamespace(
                        phase="Running",
                        pod_ip="10.0.0.15",
                        start_time="2026-04-06T20:00:00Z",
                        qos_class="Burstable",
                        container_statuses=[SimpleNamespace(restart_count=1)],
                    ),
                )
            ]
        )

    def list_namespaced_service(self, namespace: str, limit: int):
        assert namespace == "rackspace"
        assert limit == 25
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    metadata=SimpleNamespace(name="api", labels={"app": "api"}),
                    spec=SimpleNamespace(
                        type="ClusterIP",
                        cluster_ip="10.0.0.1",
                        ports=[SimpleNamespace(port=80, protocol="TCP", target_port=8080)],
                    ),
                )
            ]
        )


class _FakeAppsV1:
    def list_namespaced_deployment(self, namespace: str, limit: int):
        assert namespace == "rackspace"
        assert limit == 25
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    metadata=SimpleNamespace(name="api", labels={"app": "api"}),
                    spec=SimpleNamespace(replicas=2),
                    status=SimpleNamespace(ready_replicas=2, available_replicas=2),
                )
            ]
        )

    def list_namespaced_stateful_set(self, namespace: str, limit: int):
        assert namespace == "rackspace"
        assert limit == 25
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    metadata=SimpleNamespace(name="db", labels={"app": "db"}),
                    spec=SimpleNamespace(replicas=1, service_name="db"),
                    status=SimpleNamespace(ready_replicas=1),
                )
            ]
        )


class _FakeStorageV1:
    def list_storage_class(self):
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    metadata=SimpleNamespace(name="fast", labels={}, annotations={}),
                    provisioner="csi.example",
                    reclaim_policy="Delete",
                    volume_binding_mode="WaitForFirstConsumer",
                    allow_volume_expansion=True,
                    mount_options=[],
                )
            ]
        )


@pytest.mark.asyncio
async def test_cluster_inventory_collects_nodes_storage_and_namespace_workloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bakery_collectors,
        "get_settings",
        lambda: SimpleNamespace(bakery_monitor_namespace="rackspace"),
    )
    monkeypatch.setattr(
        bakery_collectors,
        "_load_kubernetes_clients",
        lambda: (_FakeCoreV1(), _FakeAppsV1(), _FakeStorageV1()),
    )

    result = await bakery_collectors.run_collection_job(
        "cluster_inventory",
        {"namespace": "rackspace", "limit": 25},
    )

    assert result["collector_type"] == "cluster_inventory"
    assert result["namespace"] == "rackspace"
    assert result["node_count"] == 2
    assert result["ready_node_count"] == 1
    assert result["storage_class_count"] == 1
    assert result["persistent_volume_count"] == 1
    assert result["persistent_volume_claim_count"] == 1
    assert result["pod_count"] == 1
    assert result["cluster_summary"]["allocatable"]["cpu_millicores"] == 7600
    assert result["cluster_summary"]["capacity"]["memory_bytes"] == 34359738368
    assert result["nodes"][0]["labels"]["topology.kubernetes.io/zone"] == "ord-a"
    assert result["nodes"][1]["schedulable"] is False
    assert result["storage_classes"][0]["name"] == "fast"
    assert result["persistent_volumes"][0]["claim_ref"] == "rackspace/data-api-0"
    assert result["persistent_volume_claims"][0]["requested_storage"] == "100Gi"
    assert result["services"][0]["ports"] == ["80/TCP -> 8080"]
    assert "nodes ready" in result["report"]["highlights"][0]
