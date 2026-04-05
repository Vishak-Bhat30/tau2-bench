#!/usr/bin/env python3
"""Comprehensive failure analysis of simulation results with verifier.

Classifies every task into error categories and finds steering showcase examples.
"""

import json
import os
import re
from collections import defaultdict, Counter
from pathlib import Path

BASE = Path("/workspace/vishak/tau2-bench/data/simulations")

DIRS = {
    "airline": BASE / "20260329_082605_airline_llm_agent_Qwen3-30B-A3B-Thinking-2507_user_simulator_Qwen3-30B-A3B-Thinking-2507",
    "retail":  BASE / "20260329_084432_retail_llm_agent_Qwen3-30B-A3B-Thinking-2507_user_simulator_Qwen3-30B-A3B-Thinking-2507",
    "telecom": BASE / "20260329_091929_telecom_llm_agent_Qwen3-30B-A3B-Thinking-2507_user_simulator_Qwen3-30B-A3B-Thinking-2507",
}

# Write tools per domain (tools that modify database state)
AIRLINE_WRITE_TOOLS = {
    "update_reservation_passengers", "update_reservation_flights",
    "update_reservation_baggages", "cancel_reservation", "book_reservation",
    "send_certificate", "transfer_to_human_agents",
}
RETAIL_WRITE_TOOLS = {
    "cancel_pending_order", "modify_pending_order_items",
    "modify_pending_order_payment", "modify_pending_order_address",
    "return_delivered_order_items", "exchange_delivered_order_items",
    "transfer_to_human_agent",
}
TELECOM_WRITE_TOOLS = {
    "update_account_info", "update_data_plan", "update_billing_preference",
    "update_mobile_settings", "update_network_settings", "restart_device",
    "reset_network", "toggle_airplane_mode", "toggle_data_saver",
    "toggle_roaming", "transfer_to_human_agent",
}

def get_reward(sim):
    """Safely get reward from simulation."""
    ri = sim.get("reward_info")
    if ri is None:
        return 0.0
    return ri.get("reward", 0.0) or 0.0

def get_breakdown(sim):
    """Safely get reward breakdown dict."""
    ri = sim.get("reward_info")
    if ri is None:
        return {}
    return ri.get("reward_breakdown", {}) or {}

def get_verifier_msgs(messages):
    """Extract [VERIFIER] messages from conversation."""
    out = []
    for m in messages:
        c = m.get("content", "") or ""
        if isinstance(c, str) and "[VERIFIER]" in c:
            out.append(c)
    return out

def get_agent_tool_calls(messages):
    """Extract tool calls made by the assistant."""
    calls = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in (m.get("tool_calls") or []):
            # Format: {id, name, arguments, requestor}
            name = tc.get("name", "")
            raw_args = tc.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    raw_args = {}
            calls.append({"name": name, "args": raw_args})
    return calls

def detect_steering(messages):
    """
    Find instances where verifier blocked a tool call and the agent changed behavior.
    Returns list of dicts: {blocked_tool, next_tool, verifier_msg}
    """
    steerings = []
    for i, m in enumerate(messages):
        c = m.get("content", "") or ""
        if not isinstance(c, str) or "[VERIFIER]" not in c:
            continue
        # Extract blocked tool name
        blocked = None
        match = re.search(r"FORBIDDEN:\s*(\S+)", c)
        if match:
            blocked = match.group(1)
        if not match:
            match = re.search(r"arguments don't match.*?for tool '?(\w+)'?", c, re.I)
            if match:
                blocked = match.group(1)

        # Find next assistant message with tool calls
        for j in range(i + 1, min(i + 5, len(messages))):
            nxt = messages[j]
            if nxt.get("role") == "assistant" and nxt.get("tool_calls"):
                next_tool = nxt["tool_calls"][0].get("name", "?")
                steerings.append({
                    "blocked": blocked or "?",
                    "next_tool": next_tool,
                    "changed": blocked and next_tool != blocked,
                    "verifier_msg": c[:200],
                })
                break
    return steerings


def classify_task(sim, domain):
    """
    Classify a single task into a failure category.
    Returns (category, sub_info_dict).
    """
    reward = get_reward(sim)
    breakdown = get_breakdown(sim)
    messages = sim.get("messages", [])
    verifier_msgs = get_verifier_msgs(messages)
    agent_calls = get_agent_tool_calls(messages)
    steerings = detect_steering(messages)
    term_reason = sim.get("termination_reason", "")

    # Determine which reward components failed
    failed_components = [k for k, v in breakdown.items() if v is not None and v < 1.0]
    passed_components = [k for k, v in breakdown.items() if v is not None and v >= 1.0]

    write_tools = {"airline": AIRLINE_WRITE_TOOLS, "retail": RETAIL_WRITE_TOOLS, "telecom": TELECOM_WRITE_TOOLS}.get(domain, set())
    agent_writes = [c for c in agent_calls if c["name"] in write_tools]

    info = {
        "reward": reward,
        "breakdown": breakdown,
        "failed_components": failed_components,
        "passed_components": passed_components,
        "verifier_count": len(verifier_msgs),
        "verifier_msgs": verifier_msgs,
        "steerings": steerings,
        "agent_writes": agent_writes,
        "total_calls": len(agent_calls),
        "term_reason": term_reason,
    }

    if reward >= 1.0:
        if verifier_msgs:
            return ("PASS_WITH_STEERING", info)
        return ("PASS_NO_VERIFIER", info)

    # Infrastructure / None reward
    ri = sim.get("reward_info")
    if ri is None:
        return ("FAIL_INFRASTRUCTURE", info)

    # Has verifier involvement?
    if verifier_msgs:
        # Verifier tried to help but task still failed
        if "DB" in failed_components:
            # DB still wrong despite verifier
            if any(s.get("changed") for s in steerings):
                return ("FAIL_VERIFIER_STEERED_BUT_DB_WRONG", info)
            else:
                return ("FAIL_VERIFIER_IGNORED_DB_WRONG", info)
        elif failed_components:
            return ("FAIL_VERIFIER_ACTIVE_COMM_OR_NL", info)
        else:
            return ("FAIL_VERIFIER_ACTIVE_UNKNOWN", info)

    # No verifier involvement — either verifier had nothing to say or task was fine
    if not failed_components:
        return ("FAIL_NO_BREAKDOWN", info)

    if "DB" in failed_components and len(failed_components) == 1:
        # Only DB failed, no verifier
        if not agent_writes:
            return ("FAIL_DB_NO_WRITES_MADE", info)
        return ("FAIL_DB_WRONG_ACTION_NO_VERIFIER", info)
    elif "COMMUNICATE" in failed_components and "DB" not in failed_components:
        return ("FAIL_COMMUNICATION_ONLY", info)
    elif "NL_ASSERTION" in failed_components and "DB" not in failed_components:
        return ("FAIL_NL_ASSERTION_ONLY", info)
    elif "ENV_ASSERTION" in failed_components and "DB" not in failed_components:
        return ("FAIL_ENV_ASSERTION_ONLY", info)
    elif "DB" in failed_components:
        other = [c for c in failed_components if c != "DB"]
        return (f"FAIL_DB_PLUS_{'_'.join(other)}", info)
    else:
        return (f"FAIL_{'_'.join(failed_components)}", info)


def analyze_domain(domain):
    """Full analysis of one domain."""
    with open(DIRS[domain] / "results.json") as f:
        data = json.load(f)
    sims = data["simulations"]

    print(f"\n{'='*80}")
    print(f" {domain.upper()} — {len(sims)} tasks")
    print(f"{'='*80}")

    total = len(sims)
    passed = sum(1 for s in sims if get_reward(s) >= 1.0)
    avg = sum(get_reward(s) for s in sims) / total
    print(f" Score: {passed}/{total} = {passed/total:.1%}  (avg reward = {avg:.3f})")

    # Classify every task
    categories = defaultdict(list)
    for s in sims:
        cat, info = classify_task(s, domain)
        categories[cat].append((s["task_id"], info))

    # Print category breakdown
    print(f"\n {'Category':<45} {'Count':>5} {'Pct':>7}")
    print(f" {'-'*57}")
    for cat in sorted(categories, key=lambda c: -len(categories[c])):
        items = categories[cat]
        pct = len(items) / total * 100
        print(f" {cat:<45} {len(items):>5} {pct:>6.1f}%")

    # Detailed task lists for each category
    print(f"\n DETAILED TASK IDs PER CATEGORY:")
    for cat in sorted(categories, key=lambda c: -len(categories[c])):
        items = categories[cat]
        tids = [str(tid)[:60] for tid, _ in items]
        print(f"\n  [{cat}] ({len(items)} tasks)")
        for tid, info in items[:15]:
            bd = info["breakdown"]
            v = info["verifier_count"]
            extra = ""
            if info["steerings"]:
                changed = sum(1 for s in info["steerings"] if s.get("changed"))
                extra = f", steered={changed}/{len(info['steerings'])}"
            term = info.get("term_reason", "")
            writes = [w["name"] for w in info["agent_writes"]]
            writes_str = ", ".join(Counter(writes).most_common(3).__iter__().__next__()[0] for _ in [] ) if False else ", ".join(f"{n}x{c}" for n, c in Counter(writes).most_common(3))
            print(f"   {str(tid)[:55]:<55} r={info['reward']:.2f} bd={bd} v={v}{extra}")
            if writes_str:
                print(f"     writes: {writes_str}")
        if len(items) > 15:
            print(f"   ... and {len(items)-15} more")

    # Steering showcase
    showcase = []
    for cat, items in categories.items():
        for tid, info in items:
            if info["steerings"]:
                for s in info["steerings"]:
                    if s.get("changed"):
                        showcase.append({
                            "task_id": tid,
                            "reward": info["reward"],
                            "category": cat,
                            "blocked": s["blocked"],
                            "next_tool": s["next_tool"],
                            "msg": s["verifier_msg"],
                        })

    if showcase:
        print(f"\n STEERING EXAMPLES ({len(showcase)}):")
        # Sort: successful steerings first
        showcase.sort(key=lambda x: -x["reward"])
        for ex in showcase[:20]:
            status = "✓ SUCCESS" if ex["reward"] >= 1.0 else f"✗ FAILED (r={ex['reward']:.2f})"
            print(f"  {status} Task {str(ex['task_id'])[:50]}")
            print(f"    Blocked: {ex['blocked']} → Changed to: {ex['next_tool']}")
            print(f"    Verifier: {ex['msg'][:120]}")

    return categories, showcase


def main():
    all_showcase = []
    all_categories = {}

    for domain in ["airline", "retail", "telecom"]:
        if not (DIRS[domain] / "results.json").exists():
            print(f"Skipping {domain}")
            continue
        cats, showcase = analyze_domain(domain)
        all_categories[domain] = cats
        all_showcase.extend([(domain, s) for s in showcase])

    # ── Grand summary ──
    print(f"\n{'='*80}")
    print(f" GRAND SUMMARY")
    print(f"{'='*80}")

    # Aggregate categories across all domains
    grand = defaultdict(int)
    grand_total = 0
    for domain, cats in all_categories.items():
        for cat, items in cats.items():
            grand[cat] += len(items)
            grand_total += len(items)

    print(f"\n Total tasks across all domains: {grand_total}")
    print(f"\n {'Category':<45} {'Count':>5} {'Pct':>7}")
    print(f" {'-'*57}")
    for cat in sorted(grand, key=lambda c: -grand[c]):
        pct = grand[cat] / grand_total * 100
        print(f" {cat:<45} {grand[cat]:>5} {pct:>6.1f}%")

    # Best showcase examples
    successful_steers = [(d, s) for d, s in all_showcase if s["reward"] >= 1.0]
    print(f"\n ★ SHOWCASE SUCCESSFUL STEERINGS: {len(successful_steers)}")
    for domain, ex in successful_steers:
        print(f"   [{domain}] Task {str(ex['task_id'])[:50]}")
        print(f"     Blocked {ex['blocked']} → Agent used {ex['next_tool']} → PASSED!")
        print(f"     Msg: {ex['msg'][:140]}")

    failed_steers = [(d, s) for d, s in all_showcase if s["reward"] < 1.0]
    print(f"\n ✗ STEERINGS THAT DID NOT LEAD TO SUCCESS: {len(failed_steers)}")
    for domain, ex in failed_steers[:10]:
        print(f"   [{domain}] Task {str(ex['task_id'])[:50]} (r={ex['reward']:.2f})")
        print(f"     Blocked {ex['blocked']} → Agent used {ex['next_tool']}")


if __name__ == "__main__":
    main()
