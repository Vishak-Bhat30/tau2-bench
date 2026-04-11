#!/usr/bin/env python3
"""Extract tau2-bench simulation results into a CSV file."""

import csv
import json
import os
import sys
from pathlib import Path

SIMULATIONS_DIR = Path(__file__).parent / "data" / "simulations"
OUTPUT_CSV = Path(__file__).parent / "all_results.csv"

REWARD_COMPONENTS = ["DB", "ENV_ASSERTION", "NL_ASSERTION", "ACTION", "COMMUNICATE"]


def extract_token_counts(messages):
    """Sum token usage across all messages, split by role."""
    agent_prompt, agent_completion = 0, 0
    user_prompt, user_completion = 0, 0
    for msg in messages:
        usage = msg.get("usage")
        if not usage:
            continue
        pt = usage.get("prompt_tokens", 0) or 0
        ct = usage.get("completion_tokens", 0) or 0
        if msg.get("role") == "assistant":
            agent_prompt += pt
            agent_completion += ct
        elif msg.get("role") == "user":
            user_prompt += pt
            user_completion += ct
    return {
        "agent_prompt_tokens": agent_prompt,
        "agent_completion_tokens": agent_completion,
        "user_prompt_tokens": user_prompt,
        "user_completion_tokens": user_completion,
        "total_prompt_tokens": agent_prompt + user_prompt,
        "total_completion_tokens": agent_completion + user_completion,
        "total_tokens": agent_prompt + agent_completion + user_prompt + user_completion,
    }


def extract_nl_assertion_details(reward_info):
    """Extract per-NL-assertion pass/fail info."""
    nl_assertions = reward_info.get("nl_assertions") or []
    details = []
    for nla in nl_assertions:
        details.append({
            "assertion": nla.get("nl_assertion", ""),
            "met": nla.get("met"),
            "justification": nla.get("justification", ""),
        })
    return details


def process_run(run_dir):
    """Process a single run directory and return rows."""
    results_path = run_dir / "results.json"
    if not results_path.exists():
        return []

    with open(results_path) as f:
        data = json.load(f)

    info = data.get("info", {})
    domain = info.get("environment_info", {}).get("domain_name", "unknown")
    agent_llm = info.get("agent_info", {}).get("llm", "unknown")
    user_llm = info.get("user_info", {}).get("llm", "unknown")
    run_name = run_dir.name

    rows = []
    for sim in data.get("simulations", []):
        ri = sim.get("reward_info")
        if ri is None:
            continue  # skip unevaluated simulations

        breakdown = ri.get("reward_breakdown") or {}
        basis = ri.get("reward_basis") or []

        # Token counts
        tokens = extract_token_counts(sim.get("messages", []))

        # NL assertion details
        nl_details = extract_nl_assertion_details(ri)
        nl_pass = sum(1 for d in nl_details if d["met"])
        nl_total = len(nl_details)

        # Count messages by role
        msgs = sim.get("messages", [])
        num_turns = sum(1 for m in msgs if m.get("role") == "assistant")

        row = {
            "run_name": run_name,
            "domain": domain,
            "agent_llm": agent_llm.split("/")[-1],
            "user_llm": user_llm.split("/")[-1],
            "task_id": sim.get("task_id", ""),
            "trial": sim.get("trial", 0),
            "reward": ri.get("reward", ""),
            "reward_basis": "|".join(basis),
            "termination_reason": sim.get("termination_reason", ""),
            "duration_sec": round(sim.get("duration", 0) or 0, 1),
            "num_turns": num_turns,
            "num_messages": len(msgs),
            "agent_cost": sim.get("agent_cost", 0),
            "user_cost": sim.get("user_cost", 0),
            # NL assertion summary
            "nl_assertions_passed": nl_pass,
            "nl_assertions_total": nl_total,
            "nl_assertions_text": " || ".join(
                f"[{'PASS' if d['met'] else 'FAIL'}] {d['assertion']}"
                for d in nl_details
            ),
        }

        # Individual reward components
        for comp in REWARD_COMPONENTS:
            if comp in breakdown:
                row[f"reward_{comp}"] = breakdown[comp]
            elif comp in basis:
                row[f"reward_{comp}"] = ""  # in basis but missing from breakdown
            else:
                row[f"reward_{comp}"] = "N/A"  # not part of this task's evaluation

        # Token counts
        row.update(tokens)

        rows.append(row)

    return rows


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else str(OUTPUT_CSV)

    all_rows = []
    run_dirs = sorted(SIMULATIONS_DIR.iterdir())
    for run_dir in run_dirs:
        if run_dir.is_dir():
            rows = process_run(run_dir)
            all_rows.append((run_dir.name, len(rows)))
            if rows:
                # Use first row's keys to build fieldnames on first batch
                if not hasattr(main, "_fieldnames"):
                    main._fieldnames = list(rows[0].keys())
                for r in rows:
                    all_rows_flat = getattr(main, "_all", [])
                    all_rows_flat.append(r)
                    main._all = all_rows_flat

    rows_flat = getattr(main, "_all", [])
    fieldnames = getattr(main, "_fieldnames", [])

    if not rows_flat:
        print("No evaluated simulations found.")
        return

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_flat)

    # Print summary
    print(f"Wrote {len(rows_flat)} rows to {output_path}")
    print()
    print("=== Per-run summary ===")
    for name, count in all_rows:
        print(f"  {name}: {count} evaluated sims")

    # Print aggregate stats
    print()
    print("=== Aggregate stats ===")
    from collections import defaultdict
    by_key = defaultdict(list)
    for r in rows_flat:
        key = (r["domain"], r["agent_llm"], r["user_llm"], r["run_name"])
        by_key[key].append(r)

    for (domain, agent, user, run), sims in sorted(by_key.items()):
        rewards = [s["reward"] for s in sims if s["reward"] != ""]
        avg_reward = sum(rewards) / len(rewards) if rewards else 0

        # Component averages (only where applicable)
        comp_avgs = {}
        for comp in REWARD_COMPONENTS:
            vals = [s[f"reward_{comp}"] for s in sims if isinstance(s[f"reward_{comp}"], (int, float))]
            if vals:
                comp_avgs[comp] = sum(vals) / len(vals)

        # Token averages
        avg_tokens = sum(s["total_tokens"] for s in sims) / len(sims)

        print(f"  {run}")
        print(f"    domain={domain}, agent={agent}, user={user}")
        print(f"    avg_reward={avg_reward:.4f} (n={len(rewards)})")
        for comp, avg in comp_avgs.items():
            print(f"    avg_{comp}={avg:.4f}")
        print(f"    avg_total_tokens={avg_tokens:.0f}")
        print()


if __name__ == "__main__":
    main()
