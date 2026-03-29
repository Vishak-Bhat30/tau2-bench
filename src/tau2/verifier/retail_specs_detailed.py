"""
Detailed retail specs with argument-level validation for all 114 tasks.

Built programmatically from tasks.json golden actions.  Each task gets:
  - forbidden_write_tools: WRITE tools NOT in the golden actions
  - allowed_write_actions: exact argument constraints from golden actions
  - required_reads_before_writes: user/order lookups that should precede writes
  - max_write_calls: 0 for info-only tasks

Retail WRITE tools:
  cancel_pending_order, exchange_delivered_order_items,
  return_delivered_order_items, modify_pending_order_address,
  modify_pending_order_items, modify_pending_order_payment,
  modify_user_address, transfer_to_human_agents
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tau2.verifier.spec import ActionConstraint, TaskSpec

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────

RETAIL_WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "return_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    # transfer_to_human_agents is GENERIC but we track it too
}

RETAIL_READ_TOOLS = {
    "get_user_details",
    "get_order_details",
    "get_product_details",
    "get_item_details",
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "list_all_product_types",
    "calculate",
}

# Which argument keys matter for each write tool
_COMPARE_KEYS = {
    "cancel_pending_order": ["order_id", "reason"],
    "exchange_delivered_order_items": ["order_id", "item_ids", "new_item_ids", "payment_method_id"],
    "return_delivered_order_items": ["order_id", "item_ids", "payment_method_id"],
    "modify_pending_order_address": ["order_id"],
    "modify_pending_order_items": ["order_id", "item_ids", "new_item_ids", "payment_method_id"],
    "modify_pending_order_payment": ["order_id", "payment_method_id"],
    "modify_user_address": ["user_id"],
    "transfer_to_human_agents": [],
}

# ── build logic ──────────────────────────────────────────────────────────────

_SPECS: dict[str, TaskSpec] | None = None


def _load_tasks() -> list[dict]:
    from tau2.utils.utils import DATA_DIR
    with open(DATA_DIR / "tau2" / "domains" / "retail" / "tasks.json") as f:
        return json.load(f)


def _build_specs() -> dict[str, TaskSpec]:
    tasks = _load_tasks()
    specs: dict[str, TaskSpec] = {}

    for task in tasks:
        task_id = str(task["id"])
        ec = task.get("evaluation_criteria", {})
        golden_actions = ec.get("actions", [])
        desc_obj = task.get("description", {})
        purpose = ""
        if isinstance(desc_obj, dict):
            purpose = desc_obj.get("purpose", "") or ""
        elif isinstance(desc_obj, str):
            purpose = desc_obj

        # Separate golden actions into reads and writes
        write_tool_names: set[str] = set()
        allowed_writes: list[ActionConstraint] = []
        seen: set[str] = set()  # dedup key
        read_order_ids: set[str] = set()
        read_user_ids: set[str] = set()

        for action in golden_actions:
            name = action["name"]
            args = action.get("arguments", {})

            if name in RETAIL_READ_TOOLS:
                # Track order/user lookups for required_reads
                if name == "get_order_details" and "order_id" in args:
                    read_order_ids.add(args["order_id"])
                elif name == "get_user_details" and "user_id" in args:
                    read_user_ids.add(args["user_id"])
                continue

            write_tool_names.add(name)

            # Build required_args from compare keys
            compare_keys = _COMPARE_KEYS.get(name, [])
            required_args = {}
            for k in compare_keys:
                if k in args:
                    required_args[k] = args[k]

            # Dedup: same tool + same key args = skip
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

        # Forbidden = all WRITE tools NOT in golden
        if allowed_writes or "transfer_to_human_agents" in write_tool_names:
            forbidden = RETAIL_WRITE_TOOLS - write_tool_names
        else:
            forbidden = RETAIL_WRITE_TOOLS.copy()

        max_writes = 0 if not allowed_writes else None

        # Build required_reads
        required_reads: list[ActionConstraint] = []
        for uid in sorted(read_user_ids):
            required_reads.append(
                ActionConstraint(tool_name="get_user_details", required_args={"user_id": uid})
            )
        for oid in sorted(read_order_ids):
            required_reads.append(
                ActionConstraint(tool_name="get_order_details", required_args={"order_id": oid})
            )

        specs[task_id] = TaskSpec(
            task_id=task_id,
            description=purpose or f"Retail task {task_id}",
            forbidden_write_tools=forbidden,
            allowed_write_actions=allowed_writes,
            required_reads_before_writes=required_reads,
            max_write_calls=max_writes,
        )

    return specs


def _ensure_loaded() -> dict[str, TaskSpec]:
    global _SPECS
    if _SPECS is None:
        _SPECS = _build_specs()
    return _SPECS


# ── public API ───────────────────────────────────────────────────────────────

def get_spec(task_id: str) -> TaskSpec:
    """Return detailed spec for a retail task (0-113)."""
    specs = _ensure_loaded()
    task_id = str(task_id)
    if task_id not in specs:
        raise ValueError(f"No retail detailed spec for task_id={task_id}")
    return specs[task_id]


def get_all_specs() -> dict[str, TaskSpec]:
    """Return all 114 retail specs."""
    return dict(_ensure_loaded())
