# Airline Tool-Call Verifier — Rule Documentation

## Overview

The verifier is a policy enforcement layer that intercepts tool calls in the orchestrator before execution. It runs a chain of rules against each call and blocks violations with actionable feedback, giving the agent a chance to self-correct and retry (up to 3 retries per tool).

The verifier operates at **three levels**:

1. **Write tool verification** — Policy + argument validation on every write tool call
2. **Read tool verification** — SLM-based argument validation on read tools (search, lookup)
3. **Completion tracking** — Task-by-task progress checking when the conversation is about to end

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                          │
│                                                         │
│  Agent calls tool ──► Verifier.verify()                 │
│                         │                               │
│                    ┌────┴────┐                           │
│                    │ READ?   │                           │
│                    └────┬────┘                           │
│              yes /      \ no                             │
│              ▼           ▼                               │
│     check_read()    check_all()                         │
│     (1 SLM rule)    (27 rules: 13 cheap + 14 SLM)       │
│              │           │                              │
│         pass/block   pass/block                         │
│                                                         │
│  User says STOP ──► Verifier.check_completion()         │
│                        │                                │
│                   SLM task-by-task audit                 │
│                   against _completed_actions             │
│                        │                                │
│                   DONE / PENDING nudge                   │
└─────────────────────────────────────────────────────────┘
```

### Rule Counts
| Category | Count |
|----------|-------|
| **Write rules (total)** | 27 |
| — Cheap rules (DB-only, zero latency) | 13 |
| — SLM rules (require small LM call) | 14 |
| **Read rules** | 1 (SLM) |
| **Grand total** | 28 |

### Verified Tools
| Tool | Type | Rules Applied |
|------|------|--------------|
| `book_reservation` | Write | 7 rules |
| `update_reservation_flights` | Write | 7 rules |
| `update_reservation_baggages` | Write | 4 rules |
| `update_reservation_passengers` | Write | 2 rules |
| `cancel_reservation` | Write | 3 rules |
| `send_certificate` | Write | 4 rules |
| `transfer_to_human_agents` | Write | 1 rule |
| `get_reservation_details` | Read | 1 rule |

### Unverified Read Tools
These read tools pass through without checks:
- `get_user_details` — Always needed, no meaningful validation
- `list_all_airports` — Static reference data
- `calculate` — Helper tool
- `get_flight_status` — Informational lookup
- `search_direct_flight` — Previously verified but SLM unreliable for multi-leg routes
- `search_onestop_flight` — Same as above

---

## BOOK_RESERVATION Rules

### 1. `rule_book_max_passengers` — CHEAP
- **What**: Checks that `len(passengers)` ≤ 5.
- **How**: Direct count from `tool_args["passengers"]`.
- **SLM**: No.

### 2. `rule_book_payment_limits` — CHEAP
- **What**: At most 1 certificate, 1 credit card, 3 gift cards in payment.
- **How**: Looks up each `payment_id` in `user.payment_methods` to determine its `source` (certificate/credit_card/gift_card), counts each type.
- **SLM**: No.

### 3. `rule_book_payment_in_profile` — CHEAP
- **What**: Every payment method must exist in the user's profile.
- **How**: Checks each `payment_id` from `tool_args["payment_methods"]` exists in `user.payment_methods`.
- **SLM**: No.

### 4. `rule_book_baggage_count` — CHEAP
- **What**: Validates `nonfree_baggages` is calculated correctly for the booking.
- **How**: Computes `free_per_passenger` from membership × cabin lookup table, calculates `max_free = free_per_pax × num_passengers`, then verifies `nonfree = max(0, total - max_free)`.
- **SLM**: No.
- **Lookup table**:
  | Membership | Basic Economy | Economy | Business |
  |------------|--------------|---------|----------|
  | Regular    | 0            | 1       | 2        |
  | Silver     | 1            | 2       | 3        |
  | Gold       | 2            | 3       | 4        |

### 5. `rule_arg_book_reservation` — SLM
- **What**: Validates that booking arguments match what the user actually requested.
- **How**: Asks SLM to extract `{origin, destination, cabin, num_passengers, flight_type}` from conversation. Compares each field against `tool_args`.
- **SLM prompt**: "Based on the conversation, what did the user request for their NEW booking? Extract these fields as JSON: {origin, destination, cabin, num_passengers, flight_type}."
- **Critical SLM instruction**: Distinguishes `basic_economy` vs `economy` — only uses `basic_economy` if user explicitly said it.
- **Fields checked**: origin (IATA code), destination (IATA code), cabin class, passenger count, flight type (one_way/round_trip).

### 6. `rule_arg_book_payment_total` — CHEAP
- **What**: Validates payment amounts don't exceed balances for gift cards and certificates.
- **How**: For each payment in `tool_args["payment_methods"]` that uses a gift_card or certificate, looks up the balance in `user.payment_methods` and checks `amount ≤ balance`.
- **SLM**: No.

### 7. `rule_book_route_validation` — CHEAP ✨ NEW
- **What**: Verifies that the flight numbers actually fly the stated route.
- **How**: Looks up each flight number in `db.flights` to get its `origin` and `destination`. Checks:
  1. First flight departs from booking's `origin`
  2. For one-way: last flight arrives at booking's `destination`
  3. For round-trip: last flight returns to booking's `origin`
- **SLM**: No. Pure DB lookup.
- **Example catch**: Agent says origin=JFK but first flight actually departs from EWR.

---

## UPDATE_RESERVATION_FLIGHTS Rules

### 8. `rule_modify_basic_economy_no_flight_change` — CHEAP
- **What**: Basic economy flights cannot be modified (only cabin upgrades/downgrades allowed).
- **How**: If current `reservation.cabin == "basic_economy"` AND new `tool_args["cabin"] == "basic_economy"`, block (means flights are changing on a basic_economy reservation).
- **SLM**: No.

### 9. `rule_modify_no_change_origin_dest_type` — SLM
- **What**: Flight modifications cannot change origin, destination, or trip type (one-way ↔ round-trip).
- **How**: First checks if flights are actually changing (if identical flight set → allowed, it's cabin-only). If flights ARE changing, asks SLM whether the user is trying to change origin/destination/trip type.
- **SLM prompt**: "Is the user trying to change the origin city, destination city, or trip type of their reservation? Answer ONLY 'yes' or 'no'."

### 10. `rule_modify_cabin_no_flown_flights` — CHEAP
- **What**: Cabin cannot be changed if any flight has already departed.
- **How**: If new cabin ≠ current cabin, checks each flight date against `CURRENT_TIME` (2024-05-15 15:00).
- **SLM**: No.

### 11. `rule_modify_payment_method` — CHEAP
- **What**: Flight modifications must be paid with a credit card or gift card (not certificates).
- **How**: Looks up `tool_args["payment_id"]` in user's payment methods, checks `source != "certificate"`.
- **SLM**: No.

### 12. `rule_modify_route_validation` — CHEAP ✨ NEW
- **What**: Verifies modified flights match the reservation's origin/destination route.
- **How**: Looks up each new flight number in `db.flights`. Checks:
  1. First flight departs from `reservation.origin`
  2. Round-trip: last flight returns to `reservation.origin`
  3. One-way: last flight arrives at `reservation.destination`
- **SLM**: No. Pure DB lookup.
- **Skip condition**: If flight numbers are identical to current (cabin-only change), skips the check.
- **Example catch**: Reservation is DTW→LAX but agent submits flights on EWR→SFO route.

### 13. `rule_arg_update_flights` — SLM ✨ MODIFIED (prior session)
- **What**: Validates cabin class and reservation ID match conversation.
- **How**: Asks SLM to extract `{cabin, reservation_id}` from conversation. Compares against `tool_args`.
- **SLM prompt**: "Based on the conversation, what is the TARGET cabin class the user wants AFTER the flight modification? Also, what reservation ID are they modifying?"
- **Critical SLM instruction**: "If the user asks to UPGRADE or CHANGE their cabin (e.g. 'upgrade to business'), the target cabin is the NEW cabin they want, NOT their current cabin."
- **Cabin values**: `basic_economy`, `economy`, `business`, `unchanged` (if user didn't request cabin change).

---

## UPDATE_RESERVATION_BAGGAGES Rules

### 14. `rule_baggage_no_removal` — CHEAP
- **What**: Users can add but not remove checked bags.
- **How**: Checks `tool_args["total_baggages"] ≥ reservation.total_baggages`.
- **SLM**: No.

### 15. `rule_baggage_nonfree_count` — CHEAP ✨ NEW
- **What**: Verifies the nonfree baggage count is mathematically correct.
- **How**: Same formula as `rule_book_baggage_count`: looks up `free_per_pax` from membership × cabin table, computes `max_free = free_per_pax × num_passengers`, checks `nonfree == max(0, total - max_free)`.
- **SLM**: No. Pure math.
- **Example catch**: Gold member with economy class gets 3 free bags per passenger. With 1 passenger and 2 total bags → nonfree should be 0, not 1.

### 16. `rule_baggage_no_insurance_after_booking` — SLM
- **What**: Insurance cannot be added after initial booking.
- **How**: Asks SLM if agent is trying to add travel insurance to existing reservation.
- **SLM prompt**: "Is the agent trying to add travel insurance to an existing reservation? Answer ONLY 'yes' or 'no'."
- **Also applies to**: `update_reservation_flights` (checked for both tools).

### 17. `rule_arg_update_baggages` — SLM
- **What**: Validates reservation ID and bag count match conversation.
- **How**: Asks SLM to extract `{reservation_id, total_bags}` from conversation. Compares against `tool_args`.
- **SLM prompt**: "Based on the conversation, what reservation is the user modifying baggage for, and how many total checked bags do they want?"

---

## UPDATE_RESERVATION_PASSENGERS Rules

### 18. `rule_passengers_no_count_change` — CHEAP
- **What**: Cannot change the number of passengers (even human agents can't).
- **How**: Checks `len(tool_args["passengers"]) == len(reservation.passengers)`.
- **SLM**: No.

### 19. `rule_arg_update_passengers` — SLM ✨ NEW (prior session)
- **What**: Validates the agent is modifying the correct reservation.
- **How**: Asks SLM to extract `{reservation_id}` from conversation, compares against `tool_args["reservation_id"]`.
- **SLM prompt**: "Based on the conversation, what reservation ID is the user modifying passengers for?"
- **Example catch**: User discusses reservation XEHM4B but agent calls update on 59XX6W.

---

## CANCEL_RESERVATION Rules

### 20. `rule_cancel_flown_flights` — CHEAP
- **What**: Cannot cancel if any flight has already departed.
- **How**: Checks each flight date against `CURRENT_TIME` (2024-05-15).
- **SLM**: No.

### 21. `rule_cancel_eligibility` — SLM
- **What**: Cancellation only allowed if one of these conditions is met:
  1. Business class reservation
  2. Booked within last 24 hours
  3. Flight cancelled by airline
  4. Has travel insurance AND reason is covered (health/weather)
- **How**: Checks conditions 1 and 2 via DB. For 3 and 4, uses SLM to extract from conversation.
- **SLM prompt 1**: "Was the user's flight cancelled by the airline? Answer ONLY 'yes' or 'no'."
- **SLM prompt 2** (only if has insurance): "What is the reason the user wants to cancel? Is the user mentioning health issue, illness, or bad weather? Answer: 'health', 'weather', 'change_of_plan', 'other'."

### 22. `rule_arg_cancel_reservation` — SLM
- **What**: Validates the agent is cancelling the correct reservation.
- **How**: Asks SLM to list all reservation IDs the user wants cancelled. If user says "all", any cancel is allowed. Otherwise checks that `tool_args["reservation_id"]` is in the mentioned set.
- **SLM prompt**: "What reservation ID(s) does the user want to cancel? List ALL reservation IDs mentioned for cancellation, comma-separated. If the user wants to cancel ALL reservations, say 'all'."

---

## SEND_CERTIFICATE Rules

### 23. `rule_certificate_eligibility` — SLM
- **What**: Only compensate if user is silver/gold OR has insurance OR flies business.
- **How**: Checks membership first (cheap). If regular, asks SLM for the reservation ID being complained about, then checks that reservation's insurance and cabin.
- **SLM prompt**: "What reservation ID is the user complaining about? Answer with ONLY the reservation ID."

### 24. `rule_certificate_amount` — SLM
- **What**: Certificate amount must follow policy: $100×passengers (cancelled flight) or $50×passengers (delayed flight).
- **How**: Gets reservation via SLM to find passenger count, then asks SLM for complaint type. If the SLM cannot identify a specific reservation ID, the rule is **skipped** (no fallback to avoid false positives).
- **SLM prompt 1**: "What reservation ID is the user complaining about?"
- **SLM prompt 2**: "Is the user complaining about a cancelled flight or a delayed flight? Answer ONLY 'cancelled' or 'delayed'."
- **Math**: `expected = rate × len(reservation.passengers)`
- **Safety**: No fallback — if reservation ID can't be identified, rule passes to avoid wrong passenger counts.

### 25. `rule_certificate_no_proactive` — SLM
- **What**: Agent must not proactively offer compensation — user must ask first.
- **How**: Asks SLM to check if the USER (not agent) explicitly requested compensation.
- **SLM prompt**: "Did the user explicitly ask for compensation, a voucher, a certificate, a refund, money, or any form of monetary gesture? Look at USER messages only. Answer ONLY 'yes' or 'no'."

### 26. `rule_arg_send_certificate` — SLM
- **What**: Certificate is sent to the correct user.
- **How**: Asks SLM for the user ID of the customer in the conversation, compares against `tool_args["user_id"]`.
- **SLM prompt**: "What is the user ID of the customer in this conversation? Answer with ONLY the user ID."

---

## TRANSFER_TO_HUMAN_AGENTS Rules

### 27. `rule_transfer_only_when_needed` — SLM
- **What**: Only transfer if user explicitly asks OR the request truly can't be handled by the automated system.
- **How**: Two-step SLM check:
  1. Did user explicitly ask for human agent? → If yes, allow.
  2. Is the user's core request something the automated system can handle (book/cancel/modify/compensate)? → If yes, block the transfer.
- **SLM prompt 1**: "Did the user explicitly ask to speak to a human agent or supervisor?"
- **SLM prompt 2**: "Is the user's core request one of these: book a flight, cancel a reservation, modify flights/cabin/baggage/passengers, or get a certificate/compensation? Answer 'yes' if it CAN be handled."

---

## READ TOOL RULES

### 28. `rule_read_get_reservation_args` — SLM
- **What**: Validates `get_reservation_details` targets the correct reservation.
- **How**: Asks SLM if the user mentioned a specific reservation ID. Only blocks if user named exactly ONE reservation ID and the agent is looking up a different one. If user said "my upcoming flight" or "all reservations" (no specific ID), all lookups pass through to allow exploration.
- **SLM prompt**: "Did the user mention a SPECIFIC reservation ID? If yes, what is it? If user did NOT mention a specific ID, say 'none'."
- **Conservative design**: Only blocks when there's a clear 1:1 mismatch. Allows iterating through all user reservations when exploring.

---

## COMPLETION TRACKING SYSTEM

The verifier tracks every successful write tool call with a human-readable summary of what was done. When the conversation is about to end (user says STOP), it performs a task-by-task audit.

### How It Works

**1. Task Extraction** (at conversation start)
- `classify_task()` uses SLM on the user's scenario instructions to extract:
  - Expected tool types (`cancel_reservation`, `update_reservation_flights`, etc.)
  - Detailed numbered task list (e.g., "1. Cancel reservation XEHM4B 2. Upgrade reservation 59XX6W to business")

**2. Action Tracking** (during conversation)
- Every successful write tool call is recorded with a summary:
  - `"Cancelled reservation ABC123"`
  - `"Updated flights on reservation XYZ to cabin=business, flights=HAT001,HAT002"`
  - `"Updated baggage on reservation OBUT9V to 2 total bags"`
  - `"Updated passengers on reservation G72NSF to [Ivan Muller, Ivan Smith]"`
  - `"Sent $200 certificate to sofia_kim_7287"`
  - `"Transferred to human agent: User needs help with..."`

**3. Completion Audit** (when user says STOP)

The SLM receives:
- The full task list from step 1
- All completed action summaries from step 2
- The conversation history

It goes through **each task ONE BY ONE** and marks it as `DONE` or `PENDING`.

**If tasks are pending**, the agent gets a structured nudge:
```
WAIT — your work is not complete. The following tasks are still pending:
PENDING: Add 2 checked bags to reservation OBUT9V
PENDING: Inform user of total savings amount

For each pending task, you MUST either:
1. Complete it now using the appropriate tool call, OR
2. Explain clearly to the user WHY it cannot be done
   (cite the specific policy rule or system limitation).

Do not end the conversation until all tasks are addressed.
```

**Key features:**
- Max 2 nudges per conversation (safety valve to prevent infinite loops)
- Requires **strong justification** for incomplete tasks — agent must cite specific policy/limitation
- Works across all domains (airline, retail, telecom)
- For telecom: also tracks user-side device actions (toggle airplane mode, reboot, etc.)

---

## Rule Execution Flow

```
Agent calls tool
    │
    ├── READ tool?
    │       │
    │       ▼
    │   Run READ_RULES (1 SLM rule)
    │       │ violation? → block with feedback
    │       │ pass? → execute tool
    │
    └── WRITE tool?
            │
            ▼
        Run CHEAP rules (13 rules, zero latency)
            │ violation? → block with feedback
            │
            ▼
        Run SLM rules (14 rules, ~0.5s each)
            │ violation? → block with feedback
            │
            ▼
        All pass → execute tool → record action summary
```

**On blocked call**: Agent gets the feedback message and can retry (up to 3 times per tool). After 3 blocks on the same tool, the call is allowed through (safety valve).

**On conversation end** (user says STOP):
```
check_completion()
    │
    ▼
SLM audits: task list vs completed actions
    │
    ├── ALL_COMPLETE → conversation ends normally
    │
    └── PENDING tasks found → nudge agent
            │
            ▼
        Agent must complete OR justify why not
```

---

## Run History & Lessons Learned

### Baseline (20260405): 29/50 = 58%
First verifier implementation with original rule set.

### Run 2 (20260406): 25/50 = 50% — REGRESSED
Added 8 new rules (31 total). Score dropped due to 5 false-positive regressions:

| Task | Rule(s) Causing Regression | Root Cause |
|------|---------------------------|------------|
| 16 | `rule_modify_flight_count` | Too strict — user legitimately changed 2-stop→nonstop (fewer legs) |
| 19 | `rule_cancel_basic_economy` | Benchmark expects some basic_economy cancellations to succeed |
| 27 | `rule_certificate_amount` | Fallback to first user reservation gave wrong passenger count |
| 30 | `rule_read_search_flight_args` + `rule_modify_flight_count` | SLM misunderstood multi-leg route context (LAS→PHX→IAH) |
| 38 | `rule_cancel_basic_economy` + `rule_certificate_amount` | Same issues as Tasks 19 + 27 |

Only 1 improvement: Task 29 flipped FAIL→PASS.

### Fixes Applied (current state: 28 rules)
- **Removed** `rule_cancel_basic_economy` — Environment already handles basic_economy restrictions
- **Removed** `rule_modify_flight_count` — Too naive for legitimate segment-count changes
- **Removed** `rule_read_search_flight_args` — SLM unreliable for multi-leg route interpretation
- **Fixed** `rule_certificate_amount` — No fallback to first reservation; skips if SLM can't identify reservation ID

### Key Lessons
- **SLM rules on complex context are risky** — Multi-leg routes and implicit references confuse the 3B model
- **Don't duplicate environment checks** — If the environment already enforces a constraint, a verifier rule only adds false-positive risk
- **Fallback heuristics are dangerous** — "Use first reservation if unsure" leads to wrong data; better to skip the check
- **Cheap DB rules are mostly safe** — But edge cases (segment-count changes) exist even for deterministic checks
