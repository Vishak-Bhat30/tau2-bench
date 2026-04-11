#!/usr/bin/env python3
"""Produce one CSV row per run directory with aggregate scores."""

import csv
import json
import os
from pathlib import Path

SIMULATIONS_DIR = Path(__file__).parent / "data" / "simulations"
OUTPUT_CSV = Path(__file__).parent / "run_summary.csv"

REWARD_COMPONENTS = ["DB", "ENV_ASSERTION", "NL_ASSERTION", "ACTION", "COMMUNICATE"]


def process_run(run_dir):
    results_path = run_dir / "results.json"
    if not results_path.exists():
        return None

    with open(results_path) as f:
        data = json.load(f)

    info = data.get("info", {})
    domain = info.get("environment_info", {}).get("domain_name", "unknown")
    agent_llm = info.get("agent_info", {}).get("llm", "unknown").split("/")[-1]
    user_llm = info.get("user_info", {}).get("llm", "unknown").split("/")[-1]

    sims = data.get("simulations", [])
    total_sims = len(sims)
    evaluated = [s for s in sims if s.get("reward_info") is not None]
    num_evaluated = len(evaluated)

    if num_evaluated == 0:
        rewards = []
    else:
        rewards = [s["reward_info"]["reward"] for s in evaluated]

    avg_reward = sum(rewards) / len(rewards) if rewards else None

    # Per-component averages
    comp_avgs = {}
    for comp in REWARD_COMPONENTS:
        vals = []
        for s in evaluated:
            bd = s["reward_info"].get("reward_breakdown") or {}
            if comp in bd:
                vals.append(bd[comp])
        comp_avgs[comp] = sum(vals) / len(vals) if vals else None

    # NL assertion stats from the nl_assertions list (not reward_breakdown)
    nl_pass = 0
    nl_total = 0
    nl_task_scores = []  # per-task: 1.0 if all NL assertions passed, else 0.0
    for s in evaluated:
        nla_list = s["reward_info"].get("nl_assertions") or []
        if nla_list:
            task_pass = sum(1 for nla in nla_list if nla.get("met"))
            task_total = len(nla_list)
            nl_pass += task_pass
            nl_total += task_total
            nl_task_scores.append(1.0 if task_pass == task_total else 0.0)
    nl_pass_rate = nl_pass / nl_total if nl_total else None
    nl_task_avg = sum(nl_task_scores) / len(nl_task_scores) if nl_task_scores else None

    # Token totals
    total_prompt = 0
    total_completion = 0
    for s in evaluated:
        for msg in s.get("messages", []):
            u = msg.get("usage")
            if u:
                total_prompt += u.get("prompt_tokens", 0) or 0
                total_completion += u.get("completion_tokens", 0) or 0
    total_tokens = total_prompt + total_completion
    avg_tokens = total_tokens / num_evaluated if num_evaluated else None

    # Average duration
    durations = [s.get("duration", 0) or 0 for s in evaluated]
    avg_duration = sum(durations) / len(durations) if durations else None

    # Average turns
    turns = [sum(1 for m in s.get("messages", []) if m.get("role") == "assistant") for s in evaluated]
    avg_turns = sum(turns) / len(turns) if turns else None

    row = {
        "run_name": run_dir.name,
        "domain": domain,
        "agent_llm": agent_llm,
        "user_llm": user_llm,
        "total_sims": total_sims,
        "evaluated_sims": num_evaluated,
        "avg_reward": round(avg_reward, 4) if avg_reward is not None else "",
        "avg_reward_DB": round(comp_avgs["DB"], 4) if comp_avgs["DB"] is not None else "",
        "avg_reward_ENV_ASSERTION": round(comp_avgs["ENV_ASSERTION"], 4) if comp_avgs["ENV_ASSERTION"] is not None else "",
        "avg_reward_NL_ASSERTION": round(comp_avgs["NL_ASSERTION"], 4) if comp_avgs["NL_ASSERTION"] is not None else "",
        "avg_reward_ACTION": round(comp_avgs["ACTION"], 4) if comp_avgs["ACTION"] is not None else "",
        "avg_reward_COMMUNICATE": round(comp_avgs["COMMUNICATE"], 4) if comp_avgs["COMMUNICATE"] is not None else "",
        "nl_assertions_passed": nl_pass,
        "nl_assertions_total": nl_total,
        "nl_assertion_pass_rate": round(nl_pass_rate, 4) if nl_pass_rate is not None else "",
        "nl_task_pass_rate": round(nl_task_avg, 4) if nl_task_avg is not None else "",
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "avg_tokens_per_sim": round(avg_tokens) if avg_tokens is not None else "",
        "avg_duration_sec": round(avg_duration, 1) if avg_duration is not None else "",
        "avg_turns": round(avg_turns, 1) if avg_turns is not None else "",
    }
    return row


def main():
    rows = []
    for run_dir in sorted(SIMULATIONS_DIR.iterdir()):
        if run_dir.is_dir():
            row = process_run(run_dir)
            if row:
                rows.append(row)

    fieldnames = list(rows[0].keys()) if rows else []

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}\n")
    fmt = "{:<8} {:<8} {:<12} {:<10} {:<6} {:<10} {:<10} {:<10} {:<10} {:<12} {:<12}"
    print(fmt.format("domain", "user", "eval/total", "avg_reward", "DB", "ENV_ASSRT", "NL_ASSRT", "ACTION", "COMMUNIC", "nl_pass_rt", "nl_task_rt"))
    print("-" * 140)
    for r in rows:
        print(fmt.format(
            r["domain"],
            r["user_llm"][:8],
            f"{r['evaluated_sims']}/{r['total_sims']}",
            str(r["avg_reward"]),
            str(r["avg_reward_DB"]),
            str(r["avg_reward_ENV_ASSERTION"]),
            str(r["avg_reward_NL_ASSERTION"]),
            str(r["avg_reward_ACTION"]),
            str(r["avg_reward_COMMUNICATE"]),
            str(r["nl_assertion_pass_rate"]),
            str(r["nl_task_pass_rate"]),
        ))


if __name__ == "__main__":
    main()
