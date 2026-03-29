"""
Auto-generated specs for all 114 retail domain tasks.

Retail tasks involve: exchanges, returns, cancellations, modifications (items,
address, payment), and transfers. The specs are generated directly from the
task evaluation_criteria (golden actions).

Retail WRITE tools:
- cancel_pending_order
- exchange_delivered_order_items
- return_delivered_order_items
- modify_pending_order_address
- modify_pending_order_items
- modify_pending_order_payment
- modify_user_address
- transfer_to_human_agents (GENERIC but state-changing)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tau2.verifier.spec import ActionConstraint, TaskSpec

logger = logging.getLogger(__name__)

RETAIL_WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "return_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
}

# Keys we use to compare write actions (order_id is the key differentiator)
_ORDER_COMPARE_KEYS = {
    "cancel_pending_order": ["order_id"],
    "exchange_delivered_order_items": ["order_id"],
    "return_delivered_order_items": ["order_id"],
    "modify_pending_order_address": ["order_id"],
    "modify_pending_order_items": ["order_id"],
    "modify_pending_order_payment": ["order_id"],
    "modify_user_address": ["user_id"],
    "transfer_to_human_agents": [],
}


def _load_retail_tasks() -> list[dict]:
    """Load the retail tasks JSON."""
    from tau2.utils.utils import DATA_DIR

    tasks_path = DATA_DIR / "tau2" / "domains" / "retail" / "tasks.json"
    with open(tasks_path) as f:
        return json.load(f)


def build_retail_specs() -> dict[str, TaskSpec]:
    """Build specs for all 114 retail tasks from the tasks.json data."""
    tasks = _load_retail_tasks()
    specs: dict[str, TaskSpec] = {}

    for task in tasks:
        task_id = task["id"]
        ec = task["evaluation_criteria"]
        description = task.get("description", {})
        purpose = description.get("purpose", "") or ""

        # Extract golden actions
        golden_actions = ec.get("actions", [])

        # Separate WRITE actions (what the agent should do)
        write_action_names = set()
        allowed_writes: list[ActionConstraint] = []
        seen_write_keys: set[tuple] = set()

        for action in golden_actions:
            name = action["name"]
            args = action.get("arguments", {})
            requestor = action.get("requestor", "assistant")
            compare_args_raw = action.get("compare_args")

            # Only care about assistant-side actions
            if requestor != "assistant":
                continue

            # Skip READ tools
            if name in (
                "get_user_details", "get_order_details", "get_product_details",
                "get_item_details", "find_user_id_by_email", "find_user_id_by_name_zip",
                "list_all_product_types", "calculate",
            ):
                continue

            write_action_names.add(name)

            # Determine compare keys
            if compare_args_raw is not None:
                compare_keys = compare_args_raw
            elif name in _ORDER_COMPARE_KEYS:
                compare_keys = _ORDER_COMPARE_KEYS[name]
            else:
                compare_keys = []

            # Build required args from compare_keys
            required_args = {}
            for k in compare_keys:
                if k in args:
                    required_args[k] = args[k]

            # Dedup: same tool+order_id shouldn't appear twice
            dedup_key = (name, frozenset(required_args.items()))
            if dedup_key in seen_write_keys:
                continue
            seen_write_keys.add(dedup_key)

            allowed_writes.append(
                ActionConstraint(
                    tool_name=name,
                    required_args=required_args,
                    compare_args=compare_keys if compare_keys else None,
                )
            )

        # Determine forbidden writes: all WRITE tools NOT in expected actions
        if allowed_writes:
            forbidden = RETAIL_WRITE_TOOLS - write_action_names
        else:
            # No writes expected = all writes forbidden
            forbidden = RETAIL_WRITE_TOOLS.copy()

        # Special case: transfer_to_human_agents is GENERIC, handle separately
        has_transfer = any(a.tool_name == "transfer_to_human_agents" for a in allowed_writes)

        # For tasks with no write actions, set max_write_calls=0
        max_writes = 0 if not allowed_writes else None

        specs[task_id] = TaskSpec(
            task_id=task_id,
            description=purpose or f"Retail task {task_id}",
            forbidden_write_tools=forbidden,
            allowed_write_actions=allowed_writes,
            max_write_calls=max_writes,
            notes=f"Expected writes: {[(a.tool_name, a.required_args) for a in allowed_writes]}",
        )

    return specs


def get_spec(task_id: str) -> TaskSpec:
    """Get the spec for a specific retail task."""
    specs = build_retail_specs()
    if task_id not in specs:
        raise ValueError(f"No retail spec for task_id={task_id}. Available: 0-113")
    return specs[task_id]
