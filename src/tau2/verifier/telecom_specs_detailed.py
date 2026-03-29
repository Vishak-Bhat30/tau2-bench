"""
Detailed telecom specs with argument-level validation for base 114 tasks.

Built programmatically from tasks.json golden actions + split_tasks.json "base" set.

Telecom agent WRITE tools:
  enable_roaming, disable_roaming, refuel_data,
  send_payment_request, resume_line, suspend_line

Telecom GENERIC tool:
  transfer_to_human_agents

The faults encoded in the task ID determine which agent writes are expected:
  - data_usage_exceeded → refuel_data(C1001, L1002, 2.0)
  - user_abroad_roaming_disabled_* → enable_roaming(C1001, L1002)
  - overdue_bill_suspension → send_payment_request + resume_line
  - lock_sim_card_pin → transfer_to_human_agents
  - contract_end_suspension → transfer_to_human_agents
  - all other faults → no agent writes (user-side fixes only)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from tau2.verifier.spec import ActionConstraint, TaskSpec

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────

TELECOM_WRITE_TOOLS = {
    "enable_roaming",
    "disable_roaming",
    "refuel_data",
    "send_payment_request",
    "resume_line",
    "suspend_line",
    # transfer_to_human_agents is GENERIC, tracked separately
}

TELECOM_READ_TOOLS = {
    "get_customer_by_id",
    "get_customer_by_name",
    "get_customer_by_phone",
    "get_bills_for_customer",
    "get_data_usage",
    "get_details_by_id",
}

# Which argument keys to compare for each write tool
_COMPARE_KEYS = {
    "enable_roaming": ["customer_id", "line_id"],
    "disable_roaming": ["customer_id", "line_id"],
    "refuel_data": ["customer_id", "line_id", "gb_amount"],
    "send_payment_request": ["customer_id", "bill_id"],
    "resume_line": ["customer_id", "line_id"],
    "suspend_line": ["customer_id", "line_id"],
    "transfer_to_human_agents": [],
}

# ── build logic ──────────────────────────────────────────────────────────────

_SPECS: dict[str, TaskSpec] | None = None


def _load_base_tasks() -> list[dict]:
    from tau2.utils.utils import DATA_DIR
    with open(DATA_DIR / "tau2" / "domains" / "telecom" / "tasks.json") as f:
        all_tasks = json.load(f)
    with open(DATA_DIR / "tau2" / "domains" / "telecom" / "split_tasks.json") as f:
        split = json.load(f)
    base_ids = set(split["base"])
    return [t for t in all_tasks if t["id"] in base_ids]


def _build_specs() -> dict[str, TaskSpec]:
    tasks = _load_base_tasks()
    specs: dict[str, TaskSpec] = {}

    for task in tasks:
        task_id = str(task["id"])
        ec = task.get("evaluation_criteria", {})
        golden_actions = ec.get("actions", [])
        ticket = task.get("ticket", "")

        # Extract agent-side write actions from golden
        write_tool_names: set[str] = set()
        allowed_writes: list[ActionConstraint] = []
        seen: set[str] = set()

        for action in golden_actions:
            name = action["name"]
            args = action.get("arguments", {})
            requestor = action.get("requestor", "assistant")

            # Only care about agent-side actions
            if requestor != "assistant":
                continue
            if name in TELECOM_READ_TOOLS:
                continue

            write_tool_names.add(name)

            compare_keys = _COMPARE_KEYS.get(name, [])
            required_args = {}
            for k in compare_keys:
                if k in args:
                    required_args[k] = args[k]

            dedup_key = name + "|" + json.dumps(required_args, sort_keys=True)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            allowed_writes.append(
                ActionConstraint(
                    tool_name=name,
                    required_args=required_args,
                    compare_args=compare_keys if compare_keys else None,
                )
            )

        # Forbidden = all WRITE tools NOT expected
        if allowed_writes or "transfer_to_human_agents" in write_tool_names:
            forbidden = TELECOM_WRITE_TOOLS - write_tool_names
        else:
            # No agent writes expected
            forbidden = TELECOM_WRITE_TOOLS.copy()

        max_writes = 0 if (not allowed_writes and "transfer_to_human_agents" not in write_tool_names) else None

        # Build description from task ID faults
        description = _describe_task(task_id, ticket)

        specs[task_id] = TaskSpec(
            task_id=task_id,
            description=description,
            forbidden_write_tools=forbidden,
            allowed_write_actions=allowed_writes,
            max_write_calls=max_writes,
        )

    return specs


def _describe_task(task_id: str, ticket: str) -> str:
    """Build a human-readable description from the task ID."""
    # Parse: [category]fault1|fault2|...[PERSONA:X]
    parts = task_id.split("]")
    category = parts[0].lstrip("[") if parts else "unknown"
    faults_str = parts[1] if len(parts) > 1 else ""
    # Remove persona suffix
    if "[PERSONA:" in faults_str:
        faults_str = faults_str.split("[PERSONA:")[0]
    faults = [f.strip() for f in faults_str.split("|") if f.strip()]
    return f"{category}: {', '.join(faults)}" if faults else category


def _ensure_loaded() -> dict[str, TaskSpec]:
    global _SPECS
    if _SPECS is None:
        _SPECS = _build_specs()
    return _SPECS


# ── public API ───────────────────────────────────────────────────────────────

def get_spec(task_id: str) -> TaskSpec:
    """Return detailed spec for a telecom base task."""
    specs = _ensure_loaded()
    task_id = str(task_id)
    if task_id not in specs:
        raise ValueError(f"No telecom detailed spec for task_id={task_id}")
    return specs[task_id]


def get_all_specs() -> dict[str, TaskSpec]:
    """Return all 114 telecom base specs."""
    return dict(_ensure_loaded())
