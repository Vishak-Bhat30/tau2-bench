#!/usr/bin/env python3
"""Comprehensive failure analysis of simulation results with verifier."""

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

def load_data(domain):
    with open(DIRS[domain] / "results.json") as f:
        return json.load(f)

def extract_verifier_messages(messages):
    """Extract [VERIFIER] messages from conversation."""
    verifier_msgs = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and "[VERIFIER]" in content:
            verifier_msgs.append(content)
    return verifier_msgs

def extract_tool_calls_and_responses(messages):
    """Extract tool calls and their responses."""
    tool_calls = []
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in (msg.get("tool_calls") or []):
                func = tc.get("function", {})
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", "{}"),
                })
    tool_responses = []
    for msg in messages:
        if msg.get("role") == "tool":
            tool_responses.append({
                "content": msg.get("content", ""),
                "error": msg.get("error", False),
                "tool_call_id": msg.get("tool_call_id", ""),
            })
    return tool_calls, tool_responses


def analyze_simulation(sim, task, domain):
    """Analyze a single simulation. Returns dict with analysis."""
    task_id = sim["task_id"]
    messages = sim.get("messages", [])
    reward_info = sim.get("reward_info", {})
    reward = reward_info.get("reward", 0)
    
    verifier_msgs = extract_verifier_messages(messages)
    tool_calls, tool_responses = extract_tool_calls_and_responses(messages)
    
    # Get evaluation criteria results
    eval_checks = reward_info.get("checks", [])
    if not eval_checks:
        # try alternative location
        eval_checks = reward_info.get("evaluation_results", [])
    
    failed_checks = []
    passed_checks = []
    for check in eval_checks:
        passed = check.get("result")
        if passed == True or passed == 1 or passed == 1.0:
            passed_checks.append(check)
        else:
            failed_checks.append(check)
    
    # Categorize failed checks
    db_fails = []
    nl_fails = []
    other_fails = []
    
    for fc in failed_checks:
        criteria = str(fc.get("criteria", fc.get("description", "")))
        check_type = str(fc.get("type", ""))
        
        # Heuristic classification of check type
        criteria_lower = criteria.lower()
        
        if check_type == "database" or any(kw in criteria_lower for kw in [
            "status", "reservation", "order", "ticket", "payment", "cancel",
            "update_", "change_", "modify", "refund", "upgrade", "cabin",
            "database", "db_check", "field", "should be", "should have",
            "amount", "balance", "plan", "subscription", "line", "roaming",
            "data_", "gb_", "contract", "port", "billing", "invoice",
            "item_id", "return", "exchange"
        ]):
            db_fails.append(criteria)
        elif any(kw in criteria_lower for kw in [
            "inform", "tell", "say", "confirm", "apologize", "mention",
            "response", "reply", "communicate", "explain", "acknowledge",
            "greeting", "thank", "sorry", "message", "customer", "agent should",
            "agent must"
        ]):
            nl_fails.append(criteria)
        else:
            other_fails.append(criteria)
    
    # Determine error category
    has_verifier = len(verifier_msgs) > 0
    is_success = reward >= 1.0
    is_partial = 0 < reward < 1.0
    
    # Check if verifier corrected the model (model changed behavior after verifier msg)
    verifier_led_to_correction = False
    if has_verifier:
        # Look at message sequence: after verifier msg, did model try a different tool?
        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            if isinstance(content, str) and "[VERIFIER]" in content:
                # Find next assistant message with tool calls
                for j in range(i+1, len(messages)):
                    if messages[j].get("role") == "assistant" and messages[j].get("tool_calls"):
                        verifier_led_to_correction = True
                        break
                break
    
    # Determine termination reason
    term_reason = sim.get("termination_reason", "")
    
    # Count write vs read tool calls
    write_tools = set()
    read_tools = set()
    for tc in tool_calls:
        name = tc["name"]
        # Common write tools
        if any(kw in name.lower() for kw in ["update", "cancel", "create", "delete", "modify", "change", "refund", "upgrade", "book", "send", "transfer", "add", "remove", "set", "enable", "disable", "port", "refuel", "renew", "return", "exchange"]):
            write_tools.add(name)
        else:
            read_tools.add(name)
    
    return {
        "task_id": task_id,
        "reward": reward,
        "is_success": is_success,
        "is_partial": is_partial,
        "num_verifier_msgs": len(verifier_msgs),
        "verifier_msgs": verifier_msgs,
        "has_verifier": has_verifier,
        "verifier_led_to_correction": verifier_led_to_correction,
        "num_tool_calls": len(tool_calls),
        "tool_calls": [tc["name"] for tc in tool_calls],
        "write_tools_used": list(write_tools),
        "read_tools_used": list(read_tools),
        "total_checks": len(eval_checks),
        "passed_checks": len(passed_checks),
        "failed_checks": len(failed_checks),
        "db_fails": db_fails,
        "nl_fails": nl_fails,
        "other_fails": other_fails,
        "term_reason": term_reason,
        "num_messages": len(messages),
        "failed_check_details": [(fc.get("criteria", "?"), fc.get("result")) for fc in failed_checks],
        "passed_check_details": [(pc.get("criteria", "?"), pc.get("result")) for pc in passed_checks],
    }


def classify_error(analysis):
    """High-level error classification."""
    if analysis["is_success"]:
        return "SUCCESS"
    
    has_v = analysis["has_verifier"]
    db_f = len(analysis["db_fails"])
    nl_f = len(analysis["nl_fails"])
    other_f = len(analysis["other_fails"])
    
    if analysis["num_messages"] < 4:
        return "INFRA_ERROR"
    
    if has_v and analysis["is_partial"]:
        return "VERIFIER_PARTIAL_STEER"
    
    if has_v and db_f > 0 and nl_f == 0:
        return "VERIFIER_ACTIVE_WRONG_ACTION"
    
    if has_v and nl_f > 0 and db_f == 0:
        return "VERIFIER_ACTIVE_NL_FAIL"
    
    if has_v and db_f > 0 and nl_f > 0:
        return "VERIFIER_ACTIVE_MIXED"
    
    if has_v:
        return "VERIFIER_ACTIVE_OTHER"
    
    # No verifier intervention
    if db_f > 0 and nl_f == 0:
        return "WRONG_ACTION_NO_VERIFIER"
    
    if nl_f > 0 and db_f == 0:
        return "NL_FAIL_ONLY"
    
    if db_f > 0 and nl_f > 0:
        return "MIXED_FAIL_NO_VERIFIER"
    
    return "OTHER_FAIL"


def print_domain_report(domain, analyses):
    total = len(analyses)
    successes = [a for a in analyses if a["is_success"]]
    failures = [a for a in analyses if not a["is_success"]]
    partials = [a for a in analyses if a["is_partial"]]
    
    avg_reward = sum(a["reward"] for a in analyses) / total if total else 0
    
    print(f"\n{'='*80}")
    print(f"  {domain.upper()} DOMAIN ANALYSIS")
    print(f"{'='*80}")
    print(f"  Total tasks: {total}")
    print(f"  Successes (reward=1.0): {len(successes)} ({100*len(successes)/total:.1f}%)")
    print(f"  Partial (0 < reward < 1): {len(partials)} ({100*len(partials)/total:.1f}%)")
    print(f"  Failures (reward=0): {len([a for a in analyses if a['reward']==0])} ({100*len([a for a in analyses if a['reward']==0])/total:.1f}%)")
    print(f"  Average reward: {avg_reward:.3f}")
    
    # Verifier stats
    with_verifier = [a for a in analyses if a["has_verifier"]]
    print(f"\n  Verifier active in: {len(with_verifier)} tasks ({100*len(with_verifier)/total:.1f}%)")
    if with_verifier:
        v_success = [a for a in with_verifier if a["is_success"]]
        v_partial = [a for a in with_verifier if a["is_partial"]]
        v_fail = [a for a in with_verifier if a["reward"] == 0]
        print(f"    Verifier tasks → Success: {len(v_success)}, Partial: {len(v_partial)}, Fail: {len(v_fail)}")
        total_v_msgs = sum(a["num_verifier_msgs"] for a in with_verifier)
        print(f"    Total verifier messages: {total_v_msgs}")
    
    # Error classification
    print(f"\n  ERROR CLASSIFICATION:")
    categories = Counter()
    category_tasks = defaultdict(list)
    for a in analyses:
        cat = classify_error(a)
        categories[cat] += 1
        category_tasks[cat].append(a["task_id"])
    
    for cat, count in categories.most_common():
        pct = 100 * count / total
        print(f"    {cat}: {count} ({pct:.1f}%)")
        # Show task IDs for small categories or important ones
        if count <= 10 or cat in ("SUCCESS", "VERIFIER_PARTIAL_STEER"):
            ids = category_tasks[cat]
            print(f"      Tasks: {ids}")
    
    # Detailed failure breakdown
    print(f"\n  STEERING EXAMPLES (verifier active → correction attempted):")
    steering_examples = [a for a in analyses if a["has_verifier"] and a["verifier_led_to_correction"]]
    for a in steering_examples:
        status = "✓ SUCCESS" if a["is_success"] else f"✗ reward={a['reward']:.2f}"
        print(f"    Task {a['task_id']}: {status}, {a['num_verifier_msgs']} verifier msgs")
        for vm in a["verifier_msgs"][:2]:
            print(f"      Verifier: {vm[:120]}...")
        if a["is_success"]:
            print(f"      ** SHOWCASE: Verifier steered model to correct answer! **")
    
    # Successful tasks - show what checks they passed
    print(f"\n  SUCCESSFUL TASKS:")
    for a in successes:
        v_note = f" (verifier: {a['num_verifier_msgs']} msgs)" if a["has_verifier"] else ""
        print(f"    Task {a['task_id']}: reward=1.0, {a['total_checks']} checks passed{v_note}")
    
    # Per-failure task details for failures
    print(f"\n  FAILED TASK DETAILS (reward < 1.0):")
    for a in sorted(failures, key=lambda x: x["reward"], reverse=True):
        cat = classify_error(a)
        v_note = f", V={a['num_verifier_msgs']}" if a["has_verifier"] else ""
        print(f"    Task {a['task_id']}: reward={a['reward']:.2f}, cat={cat}, "
              f"checks={a['passed_checks']}/{a['total_checks']}{v_note}")
        if a["db_fails"]:
            for df in a["db_fails"][:2]:
                print(f"      DB FAIL: {df[:100]}")
        if a["nl_fails"]:
            for nf in a["nl_fails"][:2]:
                print(f"      NL FAIL: {nf[:100]}")
        if a["other_fails"]:
            for of_ in a["other_fails"][:2]:
                print(f"      OTHER FAIL: {of_[:100]}")
    
    return analyses, categories, category_tasks


def find_showcase_examples(all_analyses):
    """Find the best showcase examples across all domains."""
    print(f"\n{'='*80}")
    print(f"  BEST SHOWCASE STEERING EXAMPLES")
    print(f"{'='*80}")
    
    showcase = []
    for domain, analyses in all_analyses.items():
        for a in analyses:
            if a["has_verifier"] and a["is_success"]:
                showcase.append((domain, a))
            elif a["has_verifier"] and a["reward"] > 0 and a["verifier_led_to_correction"]:
                showcase.append((domain, a))
    
    if not showcase:
        print("  No clear showcase examples found (verifier active + success)")
        # Look for partial successes
        print("\n  PARTIAL STEERING (verifier active, partial reward):")
        for domain, analyses in all_analyses.items():
            for a in analyses:
                if a["has_verifier"] and a["reward"] > 0:
                    print(f"    [{domain}] Task {a['task_id']}: reward={a['reward']:.2f}, "
                          f"{a['num_verifier_msgs']} verifier msgs")
                    for vm in a["verifier_msgs"][:2]:
                        print(f"      {vm[:150]}")
    else:
        for domain, a in showcase:
            print(f"\n  [{domain.upper()}] Task {a['task_id']}: reward={a['reward']:.2f}")
            print(f"    Verifier messages: {a['num_verifier_msgs']}")
            for vm in a["verifier_msgs"]:
                print(f"    V: {vm[:200]}")
            print(f"    Tool calls: {a['tool_calls']}")
            print(f"    Checks: {a['passed_checks']}/{a['total_checks']} passed")


def print_summary(all_results):
    print(f"\n{'='*80}")
    print(f"  CROSS-DOMAIN SUMMARY")
    print(f"{'='*80}")
    
    all_cats = Counter()
    for domain, (analyses, categories, _) in all_results.items():
        total = len(analyses)
        succ = sum(1 for a in analyses if a["is_success"])
        avg_r = sum(a["reward"] for a in analyses) / total
        verifier_active = sum(1 for a in analyses if a["has_verifier"])
        print(f"\n  {domain.upper()}: {succ}/{total} success ({100*succ/total:.1f}%), "
              f"avg_reward={avg_r:.3f}, verifier_active={verifier_active}")
        for cat, count in categories.most_common():
            all_cats[cat] += count
    
    grand_total = sum(len(v[0]) for v in all_results.values())
    print(f"\n  OVERALL ({grand_total} tasks):")
    for cat, count in all_cats.most_common():
        print(f"    {cat}: {count} ({100*count/grand_total:.1f}%)")


# Main execution
all_analyses = {}
all_results = {}

for domain in ["airline", "retail", "telecom"]:
    print(f"\nLoading {domain}...")
    data = load_data(domain)
    tasks = {t["id"]: t for t in data.get("tasks", [])}
    simulations = data.get("simulations", [])
    
    analyses = []
    for sim in simulations:
        task = tasks.get(sim["task_id"], {})
        a = analyze_simulation(sim, task, domain)
        analyses.append(a)
    
    all_analyses[domain] = analyses
    analyses_result, categories, category_tasks = print_domain_report(domain, analyses)
    all_results[domain] = (analyses, categories, category_tasks)

find_showcase_examples(all_analyses)
print_summary(all_results)
