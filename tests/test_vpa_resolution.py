"""Tests for Vertical Pod Autoscaler policy resolution."""

import pytest

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
