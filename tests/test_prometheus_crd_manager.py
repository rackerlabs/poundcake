from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.prometheus_crd_manager import PrometheusCRDManager


class _ExplodingCustomAPI:
    def get_namespaced_custom_object(self, **kwargs):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_get_prometheus_rule_handles_lookup_error_without_reserved_logging_crash() -> None:
    manager = PrometheusCRDManager()
    manager.settings = SimpleNamespace(prometheus_crd_namespace="rackspace")
    manager.custom_api = _ExplodingCustomAPI()

    result = await manager.get_prometheus_rule("rules-file")

    assert result is None
