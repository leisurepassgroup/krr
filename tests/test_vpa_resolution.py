"""Tests for Vertical Pod Autoscaler policy resolution."""

from types import SimpleNamespace

import pytest

from robusta_krr.core.integrations.kubernetes import ClusterLoader
from robusta_krr.utils.vpa import resolve_vpa_control_for_container


def test_no_spec_returns_none() -> None:
    assert resolve_vpa_control_for_container({}, "app") is None


def test_mode_off_returns_none() -> None:
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {"containerName": "app", "mode": "Off"},
            ]
        }
    }
    assert resolve_vpa_control_for_container(spec, "app") is None


def test_update_mode_off_returns_none() -> None:
    # updateMode Off => VPA only computes recommendations, never applies them: KRR should still recommend.
    spec = {
        "updatePolicy": {"updateMode": "Off"},
        "resourcePolicy": {
            "containerPolicies": [
                {"containerName": "app", "controlledResources": ["cpu", "memory"]},
            ]
        },
    }
    assert resolve_vpa_control_for_container(spec, "app") is None


@pytest.mark.parametrize("update_mode", ["Initial", "Recreate", "Auto", None])
def test_update_mode_active_is_managed(update_mode) -> None:
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {"containerName": "app", "controlledResources": ["cpu"], "controlledValues": "RequestsOnly"}
            ]
        },
    }
    if update_mode is not None:
        spec["updatePolicy"] = {"updateMode": update_mode}
    vpa = resolve_vpa_control_for_container(spec, "app")
    assert vpa is not None
    assert vpa.cpu_requests_managed and not vpa.cpu_limits_managed


def test_default_policy_both_resources_requests_and_limits() -> None:
    spec = {"resourcePolicy": {}}
    vpa = resolve_vpa_control_for_container(spec, "any")
    assert vpa is not None
    assert vpa.cpu_requests_managed and vpa.cpu_limits_managed
    assert vpa.memory_requests_managed and vpa.memory_limits_managed


def test_requests_only() -> None:
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {
                    "containerName": "app",
                    "controlledResources": ["cpu", "memory"],
                    "controlledValues": "RequestsOnly",
                }
            ]
        }
    }
    vpa = resolve_vpa_control_for_container(spec, "app")
    assert vpa is not None
    assert vpa.cpu_requests_managed and not vpa.cpu_limits_managed
    assert vpa.memory_requests_managed and not vpa.memory_limits_managed


def test_limits_only() -> None:
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {
                    "containerName": "app",
                    "controlledResources": ["cpu", "memory"],
                    "controlledValues": "LimitsOnly",
                }
            ]
        }
    }
    vpa = resolve_vpa_control_for_container(spec, "app")
    assert vpa is not None
    assert not vpa.cpu_requests_managed and vpa.cpu_limits_managed
    assert not vpa.memory_requests_managed and vpa.memory_limits_managed


def test_cpu_only_controlled_resources() -> None:
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {
                    "containerName": "app",
                    "controlledResources": ["cpu"],
                    "controlledValues": "RequestsAndLimits",
                }
            ]
        }
    }
    vpa = resolve_vpa_control_for_container(spec, "app")
    assert vpa is not None
    assert vpa.cpu_requests_managed and vpa.cpu_limits_managed
    assert not vpa.memory_requests_managed and not vpa.memory_limits_managed


def test_wildcard_container_name() -> None:
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {
                    "containerName": "*",
                    "controlledResources": ["memory"],
                    "controlledValues": "RequestsOnly",
                }
            ]
        }
    }
    vpa = resolve_vpa_control_for_container(spec, "sidecar")
    assert vpa is not None
    assert not vpa.cpu_requests_managed
    assert vpa.memory_requests_managed and not vpa.memory_limits_managed


def test_exact_name_beats_wildcard() -> None:
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {
                    "containerName": "*",
                    "controlledResources": ["cpu", "memory"],
                    "controlledValues": "RequestsAndLimits",
                },
                {
                    "containerName": "app",
                    "controlledResources": ["cpu"],
                    "controlledValues": "RequestsOnly",
                },
            ]
        }
    }
    vpa = resolve_vpa_control_for_container(spec, "app")
    assert vpa is not None
    assert vpa.cpu_requests_managed and not vpa.cpu_limits_managed
    assert not vpa.memory_requests_managed


@pytest.mark.parametrize("cv", ["RequestsAndLimits", None])
def test_requests_and_limits_default(cv: str | None) -> None:
    policy = {"containerName": "app", "controlledResources": ["cpu", "memory"]}
    if cv is not None:
        policy["controlledValues"] = cv
    spec = {"resourcePolicy": {"containerPolicies": [policy]}}
    vpa = resolve_vpa_control_for_container(spec, "app")
    assert vpa is not None
    assert vpa.cpu_requests_managed and vpa.cpu_limits_managed
    assert vpa.memory_requests_managed and vpa.memory_limits_managed


def test_empty_controlled_resources_no_management() -> None:
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {"containerName": "app", "controlledResources": []},
            ]
        }
    }
    assert resolve_vpa_control_for_container(spec, "app") is None


def _loader_with_vpas(vpa_by_workload: dict) -> ClusterLoader:
    loader = ClusterLoader.__new__(ClusterLoader)
    loader._ClusterLoader__vpa_spec_by_workload = vpa_by_workload
    loader._ClusterLoader__owner_object_cache = {}
    # False is the "dynamic client unavailable" sentinel: avoids real API calls in unit tests.
    loader._ClusterLoader__dynamic_client = False
    loader._ClusterLoader__vpa_owner_chain_max_depth = 5
    return loader


def _owner(kind: str, name: str, api_version: str = "monitoring.coreos.com/v1"):
    return SimpleNamespace(kind=kind, name=name, api_version=api_version)


def _mock_workload(namespace: str, name: str, owner_kind=None, owner_name=None, owners=None):
    if owners is None:
        owners = []
        if owner_kind and owner_name:
            owners = [_owner(owner_kind, owner_name)]
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=namespace, owner_references=owners)
    )


def test_find_vpa_direct_match() -> None:
    spec = {"resourcePolicy": {}}
    loader = _loader_with_vpas({("default", "Deployment", "web"): spec})
    item = _mock_workload("default", "web")

    result = loader._ClusterLoader__find_vpa_spec_for_workload(item, "default", "Deployment", "web")
    assert result is spec


def test_find_vpa_via_owner_reference_crd() -> None:
    # VPA targets the Alertmanager CRD; KRR scans the generated StatefulSet that the CRD owns.
    spec = {
        "resourcePolicy": {
            "containerPolicies": [
                {"containerName": "*", "controlledResources": ["cpu"], "controlledValues": "RequestsOnly"}
            ]
        }
    }
    loader = _loader_with_vpas({("observability", "Alertmanager", "kube-prometheus-stack-alertmanager"): spec})
    item = _mock_workload(
        "observability",
        "alertmanager-kube-prometheus-stack-alertmanager",
        owner_kind="Alertmanager",
        owner_name="kube-prometheus-stack-alertmanager",
    )

    result = loader._ClusterLoader__find_vpa_spec_for_workload(
        item, "observability", "StatefulSet", "alertmanager-kube-prometheus-stack-alertmanager"
    )
    assert result is spec


def test_find_vpa_no_match() -> None:
    loader = _loader_with_vpas({("default", "Deployment", "other"): {"resourcePolicy": {}}})
    item = _mock_workload("default", "web", owner_kind="ReplicaSet", owner_name="web-abc123")

    result = loader._ClusterLoader__find_vpa_spec_for_workload(item, "default", "Deployment", "web")
    assert result is None


def test_find_vpa_multi_level_owner_chain() -> None:
    # workload -> intermediate CRD -> top CRD (which the VPA targets).
    spec = {"resourcePolicy": {}}
    loader = _loader_with_vpas({("ns", "TopCRD", "root"): spec})

    intermediate = SimpleNamespace(
        metadata=SimpleNamespace(
            name="mid", namespace="ns", owner_references=[_owner("TopCRD", "root")]
        )
    )

    def fake_fetch(namespace, api_version, kind, name):
        if (namespace, kind, name) == ("ns", "MidCRD", "mid"):
            return intermediate
        return None

    loader._ClusterLoader__fetch_owner_object = fake_fetch  # type: ignore

    item = _mock_workload("ns", "workload", owner_kind="MidCRD", owner_name="mid")
    result = loader._ClusterLoader__find_vpa_spec_for_workload(item, "ns", "StatefulSet", "workload")
    assert result is spec


def test_find_vpa_owner_chain_depth_limit() -> None:
    # No VPA anywhere in the chain; ensure traversal terminates and returns None.
    loader = _loader_with_vpas({("ns", "Unrelated", "x"): {"resourcePolicy": {}}})

    def fake_fetch(namespace, api_version, kind, name):
        # Each owner points to another owner forever; depth limit must stop this.
        return SimpleNamespace(
            metadata=SimpleNamespace(
                name=name, namespace=namespace, owner_references=[_owner(kind, name + "-parent")]
            )
        )

    loader._ClusterLoader__fetch_owner_object = fake_fetch  # type: ignore

    item = _mock_workload("ns", "workload", owner_kind="ChainCRD", owner_name="c0")
    result = loader._ClusterLoader__find_vpa_spec_for_workload(item, "ns", "StatefulSet", "workload")
    assert result is None
