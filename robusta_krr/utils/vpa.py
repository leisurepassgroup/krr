"""Resolve Vertical Pod Autoscaler container policy for KRR recommendations."""

from __future__ import annotations

import logging
from typing import Any, Optional

from robusta_krr.core.models.objects import VPAData

logger = logging.getLogger("krr")

# Per VPA API: if controlledValues is unset, RequestsAndLimits is used when both CPU and memory are controlled.
_DEFAULT_CONTROLLED_VALUES = "RequestsAndLimits"


def _pick_container_policy(container_policies: list[dict[str, Any]], container_name: str) -> Optional[dict[str, Any]]:
    """Match VPA container policy: exact name first, then wildcard ``*``."""
    exact = [p for p in container_policies if p.get("containerName") == container_name]
    if exact:
        return exact[0]
    wild = [p for p in container_policies if p.get("containerName") == "*"]
    if wild:
        return wild[0]
    return None


def _build_vpa_data(cpu_on: bool, mem_on: bool, controlled_values: str) -> VPAData:
    cv = controlled_values or _DEFAULT_CONTROLLED_VALUES
    if cv == "RequestsOnly":
        return VPAData(
            cpu_requests_managed=cpu_on,
            cpu_limits_managed=False,
            memory_requests_managed=mem_on,
            memory_limits_managed=False,
        )
    if cv == "LimitsOnly":
        return VPAData(
            cpu_requests_managed=False,
            cpu_limits_managed=cpu_on,
            memory_requests_managed=False,
            memory_limits_managed=mem_on,
        )
    # RequestsAndLimits (default)
    return VPAData(
        cpu_requests_managed=cpu_on,
        cpu_limits_managed=cpu_on,
        memory_requests_managed=mem_on,
        memory_limits_managed=mem_on,
    )


def resolve_vpa_control_for_container(vpa_spec: dict[str, Any], container_name: str) -> Optional[VPAData]:
    """
    Given a VPA ``spec`` (only the spec object), return which request/limit fields VPA manages for ``container_name``.

    Returns ``None`` if the container is excluded (mode ``Off``) or the spec is empty.
    """
    if not vpa_spec:
        return None

    policies = (vpa_spec.get("resourcePolicy") or {}).get("containerPolicies")
    policies = policies or []

    policy: Optional[dict[str, Any]]
    if not policies:
        policy = {}
    else:
        policy = _pick_container_policy(policies, container_name)
        if policy is None:
            # Policies exist but none matched this container — use VPA default (same as no policy list).
            policy = {}

    mode = policy.get("mode")
    if mode == "Off":
        return None

    controlled_resources = policy.get("controlledResources")
    if controlled_resources is None:
        cpu_on, mem_on = True, True
    elif len(controlled_resources) == 0:
        cpu_on, mem_on = False, False
    else:
        cpu_on = any(str(r).lower() == "cpu" for r in controlled_resources)
        mem_on = any(str(r).lower() == "memory" for r in controlled_resources)

    controlled_values = policy.get("controlledValues") or _DEFAULT_CONTROLLED_VALUES
    data = _build_vpa_data(cpu_on, mem_on, controlled_values)
    if not (
        data.cpu_requests_managed
        or data.cpu_limits_managed
        or data.memory_requests_managed
        or data.memory_limits_managed
    ):
        return None
    return data
