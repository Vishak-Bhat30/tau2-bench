# Telecom Spec — Verification Types

This document categorizes every rule in `telecom_policy_spec.py` by the **type of verification** it performs.

---

## Verification Type 1: Precondition Check (DB State)

These rules look up the current database state and verify a **precondition** is met before allowing the tool call. No LLM/SLM is needed — they are purely deterministic.

| Rule | Tool | What It Checks |
|---|---|---|
| `rule_refuel_max_2gb` | `refuel_data` | `gb_amount` arg ≤ 2.0 |
| `rule_refuel_line_active` | `refuel_data` | Line status == "Active" in DB |
| `rule_payment_bill_must_be_overdue` | `send_payment_request` | Bill status == "Overdue" in DB |
| `rule_payment_no_duplicate_awaiting` | `send_payment_request` | No other bill for this customer has status "Awaiting Payment" |
| `rule_resume_contract_not_expired` | `resume_line` | `line.contract_end_date` ≥ current date |
| `rule_resume_all_bills_paid` | `resume_line` | Customer has zero bills with status "Overdue" |
| `rule_customer_lookup_name_requires_dob` | `get_customer_by_name` | `dob` arg is non-empty |

**Count: 7 rules** — These are the `CHEAP_RULES` (no SLM call needed).

---

## Verification Type 2: Argument Accuracy (SLM-based)

These rules use a small language model (SLM) to extract what the user **actually discussed** in the conversation, then compare it to the tool arguments. They catch cases where the agent passes the wrong ID/phone number.

| Rule | Tool | What It Checks |
|---|---|---|
| `rule_arg_refuel_line` | `refuel_data` | `line_id` arg matches the line/phone the user mentioned |
| `rule_arg_payment_bill` | `send_payment_request` | `bill_id` arg matches the bill the user discussed |
| `rule_arg_resume_line` | `resume_line` | `line_id` + `customer_id` args match what the user discussed; also checks customer owns the line |
| `rule_arg_enable_roaming_line` | `enable_roaming` | `line_id` + `customer_id` args match the user's line; also checks customer owns the line |

**Count: 4 rules**

**How they work:**
1. SLM is asked: *"What phone number/line/bill did the user mention?"*
2. SLM answer is normalized (strip dashes, spaces, lowercase)
3. Compared against the tool arg's value and the corresponding DB record (phone number, line ID)
4. Fallback: also checks if the ID appears anywhere in the raw conversation text

---

## Verification Type 3: Policy Constraint (SLM-based)

These rules use the SLM to determine whether the **action itself** is appropriate given the conversational context, not just whether the arguments are correct.

| Rule | Tool | What It Checks |
|---|---|---|
| `rule_suspend_valid_reason` | `suspend_line` | Suspension `reason` arg is related to overdue bill or expired contract (not an arbitrary reason) |
| `rule_transfer_only_when_needed` | `transfer_to_human_agents` | User's request genuinely can't be handled by the available tools |
| `rule_disable_roaming_not_while_traveling` | `disable_roaming` | User is not currently traveling/abroad and needing data connectivity |
| `rule_refuel_only_when_data_exceeded` | `refuel_data` | If data usage is well below the limit, refueling during troubleshooting is premature (user must have explicitly requested it) |

**Count: 4 rules**

**How they work:**
1. SLM is asked a yes/no or classification question about the conversation context
2. If the answer indicates a policy violation, the rule returns a feedback message
3. These are the most "judgmental" rules — they reason about intent, not just data

---

## Summary by Verification Type

| Type | Description | Method | Count | Cost |
|---|---|---|---|---|
| **Precondition Check** | DB state must satisfy a condition before the tool call is allowed | DB lookup only | 7 | Cheap (no LLM) |
| **Argument Accuracy** | Tool args must match what the user discussed | SLM extraction + string match | 4 | 1 SLM call each |
| **Policy Constraint** | The action itself must be appropriate given the context | SLM classification | 4 | 1 SLM call each |

**Total: 15 rules** (7 cheap + 8 SLM)

---

## How They Flow at Runtime

```
Agent makes a tool call
        │
        ▼
┌─────────────────────┐
│  Is it a READ tool? │──yes──▶ Skip policy checks (except get_customer_by_name)
└────────┬────────────┘
         │ no (WRITE tool)
         ▼
┌─────────────────────────────┐
│  Run CHEAP_RULES (7 rules)  │──violation──▶ Return "[VERIFIER] ..." feedback
│  DB lookups only            │
└────────┬────────────────────┘
         │ all pass
         ▼
┌──────────────────────────────────┐
│  Run SLM_RULES (8 rules)        │──violation──▶ Return "[VERIFIER] ..." feedback
│  Argument accuracy + policy      │
│  (skipped if cheap_only=True)    │
└────────┬─────────────────────────┘
         │ all pass
         ▼
    Tool call ALLOWED
```
