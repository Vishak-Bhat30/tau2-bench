"""
Generate TaskSpecs from (user_scenario + policy + tools) using an LLM.

This script reads the user scenario for each task, the domain policy, and
the list of available tools, then asks the LLM to determine:
- Which WRITE tools should the agent call (and with what key arguments)?
- Which WRITE tools should the agent NOT call?
- What's the maximum number of WRITE calls expected?

NO evaluation_criteria or golden actions are used — only what the policy
and user request tell us.

Usage:
    export OPENAI_API_KEY="dummy"
    export OPENAI_API_BASE="http://localhost:8000/v1"

    python -m tau2.verifier.generate_specs --domain airline
    python -m tau2.verifier.generate_specs --domain retail
    python -m tau2.verifier.generate_specs --domain telecom
    python -m tau2.verifier.generate_specs --domain all
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

from tau2.utils.utils import DATA_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

AIRLINE_WRITE_TOOLS = [
    "book_reservation",
    "cancel_reservation",
    "update_reservation_flights",
    "update_reservation_baggages",
    "update_reservation_passengers",
    "send_certificate",
]

AIRLINE_READ_TOOLS = [
    "get_user_details",
    "get_reservation_details",
    "get_flight_status",
    "list_all_airports",
    "search_direct_flight",
    "search_onestop_flight",
]

AIRLINE_GENERIC_TOOLS = ["calculate", "transfer_to_human_agents"]

RETAIL_WRITE_TOOLS = [
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "return_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
]

RETAIL_READ_TOOLS = [
    "find_user_id_by_name_zip",
    "find_user_id_by_email",
    "get_user_details",
    "get_order_details",
    "get_product_details",
    "get_item_details",
    "list_all_product_types",
]

RETAIL_GENERIC_TOOLS = ["calculate", "transfer_to_human_agents"]

TELECOM_WRITE_TOOLS = [
    "send_payment_request",
    "resume_line",
    "enable_roaming",
    "disable_roaming",
    "refuel_data",
    "suspend_line",
]

TELECOM_READ_TOOLS = [
    "get_customer_by_phone",
    "get_customer_by_id",
    "get_customer_by_name",
    "get_details_by_id",
    "get_bills_for_customer",
    "get_data_usage",
]

TELECOM_GENERIC_TOOLS = ["transfer_to_human_agents"]


def _get_tools_for_domain(domain: str) -> tuple[list[str], list[str], list[str]]:
    """Return (write_tools, read_tools, generic_tools) for a domain."""
    if domain == "airline":
        return AIRLINE_WRITE_TOOLS, AIRLINE_READ_TOOLS, AIRLINE_GENERIC_TOOLS
    elif domain == "retail":
        return RETAIL_WRITE_TOOLS, RETAIL_READ_TOOLS, RETAIL_GENERIC_TOOLS
    elif domain in ("telecom", "telecom-workflow"):
        return TELECOM_WRITE_TOOLS, TELECOM_READ_TOOLS, TELECOM_GENERIC_TOOLS
    else:
        raise ValueError(f"Unknown domain: {domain}")


def _load_policy(domain: str) -> str:
    """Load the domain policy text."""
    if domain == "airline":
        path = DATA_DIR / "tau2" / "domains" / "airline" / "policy.md"
    elif domain == "retail":
        path = DATA_DIR / "tau2" / "domains" / "retail" / "policy.md"
    elif domain in ("telecom", "telecom-workflow"):
        main = DATA_DIR / "tau2" / "domains" / "telecom" / "main_policy.md"
        tech = DATA_DIR / "tau2" / "domains" / "telecom" / "tech_support_manual.md"
        return main.read_text() + "\n\n" + tech.read_text()
    else:
        raise ValueError(f"Unknown domain: {domain}")
    return path.read_text()


def _load_tasks(domain: str) -> list[dict]:
    """Load tasks for domain. Returns list of raw task dicts."""
    d = domain if domain != "telecom-workflow" else "telecom"
    tasks_path = DATA_DIR / "tau2" / "domains" / d / "tasks.json"
    with open(tasks_path) as f:
        return json.load(f)


def _extract_user_scenario(task: dict) -> str:
    """Extract a human-readable scenario string from a task (no eval criteria)."""
    us = task.get("user_scenario", {})
    instr = us.get("instructions", {})
    parts = []
    if instr.get("reason_for_call"):
        parts.append(f"Reason for call: {instr['reason_for_call']}")
    if instr.get("known_info"):
        parts.append(f"Known info: {instr['known_info']}")
    if instr.get("task_instructions"):
        parts.append(f"Additional instructions: {instr['task_instructions']}")
    if instr.get("unknown_info"):
        parts.append(f"Unknown info: {instr['unknown_info']}")

    # Also include description.purpose if present (NOT eval criteria)
    desc = task.get("description", {})
    if desc and isinstance(desc, dict) and desc.get("purpose"):
        parts.append(f"Purpose: {desc['purpose']}")

    return "\n".join(parts) if parts else "No scenario provided."


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert policy analyst for a customer service domain. Your job is to analyze a customer's request against the domain policy and determine which tool calls the agent should and should NOT make.

You will be given:
1. The domain POLICY (the rules the agent must follow)
2. The list of available WRITE tools (tools that modify state)
3. The list of available READ tools (tools that only read information)
4. A customer SCENARIO (what the user is asking for)

Based ONLY on the policy and the scenario, you must determine:

A) **allowed_write_actions**: Which WRITE tools should the agent call to handle this request? For each, specify the tool name and any key arguments you can determine from the scenario (e.g. order_id, reservation_id, user_id). Only include arguments that are explicitly stated in the scenario.

B) **forbidden_write_tools**: Which WRITE tools should the agent definitely NOT call? These are tools that would violate the policy for this particular scenario. If there's a good reason the agent might need to use a tool, don't forbid it.

C) **max_write_calls**: What is the maximum number of WRITE tool calls expected? Use 0 if the agent should make NO writes (e.g. policy says to refuse the request). Use null if there's no clear limit.

D) **transfer_to_human**: Should the agent transfer to a human agent? true/false.

E) **reasoning**: Brief explanation of why these tools are allowed/forbidden for this scenario.

IMPORTANT RULES:
- Base your analysis ONLY on the policy and scenario. Do not guess or assume information not present.
- If the scenario asks to cancel something but the policy says cancellation is not allowed in this case, then cancel should be FORBIDDEN and max_write_calls should be 0.
- If the policy says the agent should refuse the request, then ALL write tools should be forbidden and max_write_calls = 0.
- transfer_to_human_agents is a GENERIC tool (not a WRITE tool) — include it in allowed_write_actions ONLY if the scenario requires escalation per policy.
- READ tools are always allowed, you don't need to list them.
- For each allowed_write_action, only include arguments that are explicitly mentioned in the scenario text (e.g., specific order IDs, reservation IDs, user IDs). Don't make up argument values.

Respond with ONLY valid JSON in this exact format:
{
  "reasoning": "...",
  "allowed_write_actions": [
    {"tool_name": "...", "required_args": {"arg1": "value1"}},
  ],
  "forbidden_write_tools": ["tool1", "tool2"],
  "max_write_calls": 0,
  "transfer_to_human": false
}"""


def _build_user_prompt(
    scenario: str,
    policy: str,
    write_tools: list[str],
    read_tools: list[str],
    generic_tools: list[str],
) -> str:
    return f"""## DOMAIN POLICY
{policy}

## AVAILABLE WRITE TOOLS (state-modifying)
{json.dumps(write_tools, indent=2)}

## AVAILABLE READ TOOLS (information-only, always allowed)
{json.dumps(read_tools, indent=2)}

## AVAILABLE GENERIC TOOLS
{json.dumps(generic_tools, indent=2)}

## CUSTOMER SCENARIO
{scenario}

Analyze this scenario against the policy and respond with the JSON specification."""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _call_llm(system: str, user: str, model: str) -> str:
    """Call the LLM via litellm and return the raw text response."""
    from litellm import completion

    response = completion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=2048,
    )
    return response.choices[0].message.content


def _parse_llm_response(raw: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code blocks and thinking tags."""
    # Strip <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # Try to find JSON in code blocks first
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------


def generate_specs_for_domain(
    domain: str,
    model: str = "openai/Qwen/Qwen3-30B-A3B-Thinking-2507",
    task_ids: list[str] | None = None,
    max_retries: int = 2,
) -> dict[str, dict]:
    """Generate specs for all tasks in a domain.

    Args:
        domain: Domain name (airline, retail, telecom).
        model: LLM model identifier.
        task_ids: Optional list of specific task IDs to generate. None = all.
        max_retries: Number of retries per task on LLM failure.

    Returns:
        Dict mapping task_id -> spec dict.
    """
    write_tools, read_tools, generic_tools = _get_tools_for_domain(domain)
    policy = _load_policy(domain)
    tasks = _load_tasks(domain)

    specs: dict[str, dict] = {}
    total = len(tasks)

    for i, task in enumerate(tasks):
        task_id = str(task["id"])
        if task_ids and task_id not in task_ids:
            continue

        scenario = _extract_user_scenario(task)
        user_prompt = _build_user_prompt(
            scenario, policy, write_tools, read_tools, generic_tools
        )

        for attempt in range(max_retries + 1):
            try:
                raw = _call_llm(SYSTEM_PROMPT, user_prompt, model)
                parsed = _parse_llm_response(raw)
                if parsed is None:
                    logger.warning(
                        f"[{domain}] Task {task_id}: Could not parse LLM response (attempt {attempt+1})"
                    )
                    if attempt < max_retries:
                        continue
                    else:
                        logger.error(
                            f"[{domain}] Task {task_id}: Failed after {max_retries+1} attempts. Raw:\n{raw[:500]}"
                        )
                        break

                # Normalize and validate the parsed spec
                spec = {
                    "task_id": task_id,
                    "domain": domain,
                    "reasoning": parsed.get("reasoning", ""),
                    "allowed_write_actions": parsed.get("allowed_write_actions", []),
                    "forbidden_write_tools": sorted(
                        parsed.get("forbidden_write_tools", [])
                    ),
                    "max_write_calls": parsed.get("max_write_calls"),
                    "transfer_to_human": parsed.get("transfer_to_human", False),
                    "scenario_summary": scenario[:200],
                }
                specs[task_id] = spec
                logger.info(
                    f"[{domain}] Task {task_id} ({i+1}/{total}): "
                    f"allowed={len(spec['allowed_write_actions'])}, "
                    f"forbidden={len(spec['forbidden_write_tools'])}, "
                    f"max_writes={spec['max_write_calls']}"
                )
                break

            except Exception as e:
                logger.warning(
                    f"[{domain}] Task {task_id}: LLM error (attempt {attempt+1}): {e}"
                )
                if attempt < max_retries:
                    time.sleep(1)
                else:
                    logger.error(
                        f"[{domain}] Task {task_id}: Failed after {max_retries+1} attempts: {e}"
                    )

    return specs


def save_specs(specs: dict[str, dict], domain: str, output_dir: Path | None = None):
    """Save generated specs to a JSON file."""
    if output_dir is None:
        output_dir = DATA_DIR / "tau2" / "domains" / domain
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "generated_specs.json"
    with open(output_path, "w") as f:
        json.dump(specs, f, indent=2)
    logger.info(f"Saved {len(specs)} specs to {output_path}")
    return output_path


def load_generated_specs(domain: str) -> dict[str, dict] | None:
    """Load previously generated specs from JSON file."""
    path = DATA_DIR / "tau2" / "domains" / domain / "generated_specs.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Generate tool-call specs from (scenario + policy) using an LLM"
    )
    parser.add_argument(
        "--domain",
        required=True,
        choices=["airline", "retail", "telecom", "all"],
        help="Domain to generate specs for",
    )
    parser.add_argument(
        "--model",
        default="openai/Qwen/Qwen3-30B-A3B-Thinking-2507",
        help="LLM model to use (litellm format)",
    )
    parser.add_argument(
        "--task-ids",
        nargs="*",
        default=None,
        help="Specific task IDs to generate (default: all)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Max retries per task on LLM failure",
    )
    args = parser.parse_args()

    domains = (
        ["airline", "retail", "telecom"] if args.domain == "all" else [args.domain]
    )

    for domain in domains:
        print(f"\n{'='*60}")
        print(f"Generating specs for {domain}")
        print(f"{'='*60}")

        specs = generate_specs_for_domain(
            domain=domain,
            model=args.model,
            task_ids=args.task_ids,
            max_retries=args.max_retries,
        )
        path = save_specs(specs, domain)
        print(f"  → Saved {len(specs)} specs to {path}")


if __name__ == "__main__":
    main()
