"""
Test verifier accuracy: 20 crafted tool calls across airline, retail, telecom.
For each, we know the expected outcome (BLOCK or PASS).
Measures precision/recall of the verifier.
"""

import json
import os
import sys

# Must run from tau2-bench root with .venv activated
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from tau2.verifier.verifier import PolicyVerifier

# ── Load real DBs ──────────────────────────────────────────────────────────
from tau2.domains.airline.data_model import FlightDB
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.telecom.data_model import TelecomDB

AIRLINE_DB_PATH = "data/tau2/domains/airline/db.json"
RETAIL_DB_PATH = "data/tau2/domains/retail/db.json"
TELECOM_DB_PATH = "data/tau2/domains/telecom/db.toml"

airline_db = FlightDB.load(AIRLINE_DB_PATH)
retail_db = RetailDB.load(RETAIL_DB_PATH)
telecom_db = TelecomDB.load(TELECOM_DB_PATH)


# ── Helper to build a fake conversation ────────────────────────────────────
def make_convo(user_msg: str, agent_msg: str = "Sure, let me help you.") -> list[dict]:
    return [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": agent_msg},
    ]


# ── Test cases ─────────────────────────────────────────────────────────────
# Each: (domain, tool_name, tool_args, user_instructions, conversation, expected)
# expected: "block" or "pass"

TEST_CASES = []

# --------------------------------------------------------------------------
# AIRLINE domain (8 tests)
# --------------------------------------------------------------------------
# Get a real reservation for testing
res_id = "4WQ150"  # user=chen_jackson_3290, business, round_trip, DFW->LAX
res = airline_db.reservations[res_id]
user_id = res.user_id  # chen_jackson_3290

# 1. cancel_reservation on a reservation with flown flights (date < 2024-05-15) — BLOCK
# 10RJ1S has flight HAT298 on 2024-05-05, economy cabin, user=james_li_5992
TEST_CASES.append({
    "id": 1,
    "domain": "airline",
    "tool_name": "cancel_reservation",
    "tool_args": {"reservation_id": "10RJ1S"},
    "user_instructions": "You are James Li (james_li_5992). You want to cancel reservation 10RJ1S.",
    "conversation": make_convo("I need to cancel my reservation 10RJ1S."),
    "expected": "block",
    "reason": "Reservation 10RJ1S has flight on 2024-05-05 (before 2024-05-15 = flown)",
})

# 2. update_reservation_baggages — try to REMOVE bags — BLOCK
TEST_CASES.append({
    "id": 2,
    "domain": "airline",
    "tool_name": "update_reservation_baggages",
    "tool_args": {"reservation_id": res_id, "total_baggages": 0, "nonfree_baggages": 0, "payment_id": "credit_card_1234"},
    "user_instructions": f"You are Chen Jackson (user id {user_id}). You want to remove all checked bags from reservation {res_id}.",
    "conversation": make_convo(f"Can you remove my checked bags from reservation {res_id}?"),
    "expected": "block",
    "reason": "Cannot remove bags (total_baggages < current count)",
})

# 3. update_reservation_flights on basic_economy with certificate payment — BLOCK
# Find a basic_economy reservation
be_res_id = None
for rid, r in airline_db.reservations.items():
    if r.cabin == "basic_economy":
        be_res_id = rid
        break
if be_res_id:
    be_res = airline_db.reservations[be_res_id]
    # Find a certificate payment in the user's payment methods
    be_user = airline_db.users[be_res.user_id]
    cert_id = None
    cc_id = None
    for pm_id, pm in be_user.payment_methods.items():
        if pm.source == "certificate":
            cert_id = pm_id
        elif pm.source == "credit_card":
            cc_id = pm_id
    # Even if no cert, test with a fake cert ID
    TEST_CASES.append({
        "id": 3,
        "domain": "airline",
        "tool_name": "update_reservation_flights",
        "tool_args": {
            "reservation_id": be_res_id,
            "cabin": "basic_economy",
            "flights": [{"flight_number": "HAT001", "date": "2024-06-01"}],
            "payment_id": cert_id or "certificate_fake",
        },
        "user_instructions": f"You are {be_user.name.first_name} {be_user.name.last_name} (user id {be_res.user_id}). You want to change flights on reservation {be_res_id}.",
        "conversation": make_convo(f"I want to change my flights on reservation {be_res_id}."),
        "expected": "block",
        "reason": "basic_economy cannot change flights / certificate cannot be used for flight changes",
    })
else:
    # Fallback: just use a flight change block for basic_economy
    TEST_CASES.append({
        "id": 3,
        "domain": "airline",
        "tool_name": "update_reservation_flights",
        "tool_args": {"reservation_id": res_id, "cabin": "business", "flights": [], "payment_id": "certificate_fake"},
        "user_instructions": f"You are Chen Jackson ({user_id}). Change flights on {res_id}.",
        "conversation": make_convo(f"Change flights on {res_id}"),
        "expected": "block",
        "reason": "certificate payment not allowed for flight changes",
    })

# 4. book_reservation with 6 passengers — BLOCK
TEST_CASES.append({
    "id": 4,
    "domain": "airline",
    "tool_name": "book_reservation",
    "tool_args": {
        "user_id": user_id,
        "origin": "JFK",
        "destination": "LAX",
        "flight_type": "one_way",
        "cabin": "economy",
        "flights": [{"flight_number": "HAT001", "date": "2024-06-01"}],
        "passengers": [
            {"first_name": f"P{i}", "last_name": "Test", "dob": "1990-01-01"}
            for i in range(6)
        ],
        "payment_methods": [{"payment_id": "credit_card_4421486", "amount": 1000}],
        "total_baggages": 0,
        "nonfree_baggages": 0,
    },
    "user_instructions": f"You are Chen ({user_id}). You want to book a flight for 6 people.",
    "conversation": make_convo("I want to book a flight for 6 passengers from JFK to LAX."),
    "expected": "block",
    "reason": "Max 5 passengers allowed",
})

# 5. book_reservation with 2 passengers, valid — PASS (cheap rules only)
# Use mia_li_3668 who has credit_card_4421486
book_user = airline_db.users["mia_li_3668"]
book_cc_pm = None
for pm_id, pm in book_user.payment_methods.items():
    if pm.source == "credit_card":
        book_cc_pm = pm_id
        break
# Find a valid one-way flight
valid_flight = None
for fid, f in airline_db.flights.items():
    if f.origin == "DFW" and f.destination == "LAX":
        valid_flight = fid
        break
TEST_CASES.append({
    "id": 5,
    "domain": "airline",
    "tool_name": "book_reservation",
    "tool_args": {
        "user_id": "mia_li_3668",
        "origin": "DFW",
        "destination": "LAX",
        "flight_type": "one_way",
        "cabin": "economy",
        "flights": [{"flight_number": valid_flight or "HAT170", "date": "2024-06-01"}],
        "passengers": [
            {"first_name": "Mia", "last_name": "Li", "dob": "1990-04-05"},
            {"first_name": "Alice", "last_name": "Li", "dob": "1992-03-15"},
        ],
        "payment_methods": [{"payment_id": book_cc_pm, "amount": 2000}],
        "total_baggages": 2,
        "nonfree_baggages": 0,  # economy = 1 free bag/pax, 2 pax = 2 free
    },
    "user_instructions": "You are Mia Li (mia_li_3668). Book a one-way from DFW to LAX for 2 passengers.",
    "conversation": make_convo("I want to book a flight from DFW to LAX for me and my sister Alice."),
    "expected": "pass",
    "reason": "Valid booking: 2 passengers, correct free bags, valid credit card payment",
})

# 6. update_reservation_passengers — change passenger count — BLOCK
TEST_CASES.append({
    "id": 6,
    "domain": "airline",
    "tool_name": "update_reservation_passengers",
    "tool_args": {
        "reservation_id": res_id,
        "passengers": [{"first_name": "Chen", "last_name": "Jackson", "dob": "1956-07-07"}],
    },
    "user_instructions": f"You are Chen ({user_id}). Update passengers on {res_id}.",
    "conversation": make_convo(f"Remove a passenger from reservation {res_id}"),
    "expected": "block",
    "reason": f"Cannot change passenger count (original has {len(res.passengers)}, trying 1)",
})

# 7. _check_tool_args: cancel with WRONG reservation_id — BLOCK (SLM check)
TEST_CASES.append({
    "id": 7,
    "domain": "airline",
    "tool_name": "cancel_reservation",
    "tool_args": {"reservation_id": "XXXXXX"},
    "user_instructions": f"You are Emma Kim (emma_kim_9957). You want to cancel reservation EHGLP3.",
    "conversation": make_convo("I need to cancel my reservation EHGLP3 please."),
    "expected": "block",
    "reason": "_check_tool_args: reservation_id XXXXXX doesn't match user mention of EHGLP3",
})

# 8. _check_tool_args: cancel with CORRECT reservation_id — PASS (from _check_tool_args perspective)
# Note: policy rules might still block (cancel_eligibility), but the tool_args check itself should pass
TEST_CASES.append({
    "id": 8,
    "domain": "airline",
    "tool_name": "cancel_reservation",
    "tool_args": {"reservation_id": "EHGLP3"},
    "user_instructions": f"You are Emma Kim (emma_kim_9957). You want to cancel reservation EHGLP3.",
    "conversation": make_convo("I need to cancel my reservation EHGLP3 please."),
    "expected": "block_or_pass",  # Policy rules may block (eligibility), but arg check should pass
    "reason": "_check_tool_args should PASS (correct ID), but SLM cancel_eligibility may BLOCK",
})

# --------------------------------------------------------------------------
# RETAIL domain (7 tests)
# --------------------------------------------------------------------------
# Use order #W2378156 (delivered, user=yusuf_rossi_9620)
ret_order_id = "#W2378156"
ret_order = retail_db.orders[ret_order_id]
ret_user_id = ret_order.user_id

# Find a pending order for cancel/modify tests
pending_order_id = None
for oid, o in retail_db.orders.items():
    if o.status == "pending":
        pending_order_id = oid
        pending_order = o
        break

# 9. cancel_pending_order on a DELIVERED order — BLOCK
TEST_CASES.append({
    "id": 9,
    "domain": "retail",
    "tool_name": "cancel_pending_order",
    "tool_args": {"order_id": ret_order_id, "reason": "no longer needed"},
    "user_instructions": f"You are Yusuf Rossi ({ret_user_id}). Cancel order {ret_order_id}.",
    "conversation": make_convo(f"I want to cancel order {ret_order_id}."),
    "expected": "block",
    "reason": f"Order {ret_order_id} status is 'delivered', not 'pending'",
})

# 10. cancel_pending_order with invalid reason — BLOCK
if pending_order_id:
    TEST_CASES.append({
        "id": 10,
        "domain": "retail",
        "tool_name": "cancel_pending_order",
        "tool_args": {"order_id": pending_order_id, "reason": "changed my mind"},
        "user_instructions": f"You are user {pending_order.user_id}. Cancel order {pending_order_id}.",
        "conversation": make_convo(f"I changed my mind, cancel {pending_order_id}."),
        "expected": "block",
        "reason": "Reason 'changed my mind' not in allowed set {no longer needed, ordered by mistake}",
    })
else:
    TEST_CASES.append({
        "id": 10,
        "domain": "retail",
        "tool_name": "cancel_pending_order",
        "tool_args": {"order_id": "#W_FAKE", "reason": "changed my mind"},
        "user_instructions": "You want to cancel an order.",
        "conversation": make_convo("Cancel my order please."),
        "expected": "block",
        "reason": "Invalid reason",
    })

# 11. cancel_pending_order with valid reason on a pending order — PASS
if pending_order_id:
    TEST_CASES.append({
        "id": 11,
        "domain": "retail",
        "tool_name": "cancel_pending_order",
        "tool_args": {"order_id": pending_order_id, "reason": "no longer needed"},
        "user_instructions": f"You are user {pending_order.user_id}. Cancel order {pending_order_id} because you no longer need it.",
        "conversation": make_convo(f"I no longer need order {pending_order_id}, please cancel it."),
        "expected": "pass",
        "reason": "Pending order + valid reason 'no longer needed'",
    })
else:
    TEST_CASES.append({
        "id": 11,
        "domain": "retail",
        "tool_name": "cancel_pending_order",
        "tool_args": {"order_id": "#W_FAKE", "reason": "no longer needed"},
        "user_instructions": "Cancel order.",
        "conversation": make_convo("Cancel my order."),
        "expected": "pass",
        "reason": "Valid reason (order may not exist, but no cheap DB rule blocks)",
    })

# 12. return_delivered_order_items on a non-delivered order — BLOCK
# Find a cancelled order
cancelled_oid = None
for oid, o in retail_db.orders.items():
    if o.status == "cancelled":
        cancelled_oid = oid
        cancelled_order = o
        break
if cancelled_oid:
    TEST_CASES.append({
        "id": 12,
        "domain": "retail",
        "tool_name": "return_delivered_order_items",
        "tool_args": {
            "order_id": cancelled_oid,
            "item_ids": ["fake_item_1"],
            "payment_method_id": "gift_card_fake",
        },
        "user_instructions": f"You are user {cancelled_order.user_id}. Return items from {cancelled_oid}.",
        "conversation": make_convo(f"I want to return items from order {cancelled_oid}."),
        "expected": "block",
        "reason": f"Order status is 'cancelled', not in {{delivered, return requested, exchange requested}}",
    })
else:
    # Use the delivered order but with a mock
    TEST_CASES.append({
        "id": 12,
        "domain": "retail",
        "tool_name": "return_delivered_order_items",
        "tool_args": {"order_id": "#W_FAKE", "item_ids": ["x"], "payment_method_id": "y"},
        "user_instructions": "Return items.",
        "conversation": make_convo("Return items."),
        "expected": "pass",
        "reason": "Order not found → no DB rule blocks (tool will error)",
    })

# 13. modify_pending_order_items with mismatched item counts — BLOCK
if pending_order_id:
    # Get one item_id from the pending order
    items = pending_order.items
    if items:
        TEST_CASES.append({
            "id": 13,
            "domain": "retail",
            "tool_name": "modify_pending_order_items",
            "tool_args": {
                "order_id": pending_order_id,
                "item_ids": [items[0].item_id],
                "new_item_ids": ["new_1", "new_2"],  # 2 new for 1 old = mismatch
                "payment_method_id": "credit_card_fake",
            },
            "user_instructions": f"Modify items in {pending_order_id}.",
            "conversation": make_convo(f"I want to modify items in my order {pending_order_id}."),
            "expected": "block",
            "reason": "Item count mismatch: 1 old item but 2 new items",
        })
    else:
        TEST_CASES.append({
            "id": 13,
            "domain": "retail",
            "tool_name": "modify_pending_order_items",
            "tool_args": {"order_id": pending_order_id, "item_ids": ["a"], "new_item_ids": ["b", "c"], "payment_method_id": "x"},
            "user_instructions": "Modify items.",
            "conversation": make_convo("Modify my order."),
            "expected": "block",
            "reason": "Item count mismatch",
        })
else:
    TEST_CASES.append({
        "id": 13,
        "domain": "retail",
        "tool_name": "modify_pending_order_items",
        "tool_args": {"order_id": "#W_FAKE", "item_ids": ["a"], "new_item_ids": ["b", "c"], "payment_method_id": "x"},
        "user_instructions": "Modify items.",
        "conversation": make_convo("Modify my order."),
        "expected": "block",
        "reason": "Item count mismatch",
    })

# 14. _check_tool_args: cancel with WRONG order_id — BLOCK (SLM)
TEST_CASES.append({
    "id": 14,
    "domain": "retail",
    "tool_name": "cancel_pending_order",
    "tool_args": {"order_id": "#W9999999", "reason": "no longer needed"},
    "user_instructions": f"You are Yusuf Rossi ({ret_user_id}). Cancel order #W2378156.",
    "conversation": make_convo("I want to cancel my order #W2378156."),
    "expected": "block",
    "reason": "_check_tool_args: order_id #W9999999 doesn't match user mention of #W2378156",
})

# 15. _check_tool_args: cancel with CORRECT order_id (but delivered → still blocked by policy)
TEST_CASES.append({
    "id": 15,
    "domain": "retail",
    "tool_name": "cancel_pending_order",
    "tool_args": {"order_id": "#W2378156", "reason": "no longer needed"},
    "user_instructions": f"You are Yusuf Rossi ({ret_user_id}). Cancel order #W2378156.",
    "conversation": make_convo("I want to cancel my order #W2378156."),
    "expected": "block",
    "reason": "Order is delivered (policy blocks), but _check_tool_args passes (correct ID)",
})

# --------------------------------------------------------------------------
# TELECOM domain (5 tests)
# --------------------------------------------------------------------------
# Customer C1001 = John Smith, lines L1001-L1003, bills B1001-B1003

# 16. refuel_data with gb_amount > 2 — BLOCK
TEST_CASES.append({
    "id": 16,
    "domain": "telecom",
    "tool_name": "refuel_data",
    "tool_args": {"customer_id": "C1001", "line_id": "L1001", "gb_amount": 3.0},
    "user_instructions": "You are John Smith (555-123-2002). You want to add 3GB of data to your line.",
    "conversation": make_convo("I need to add 3GB of data to my line L1001."),
    "expected": "block",
    "reason": "refuel_data max is 2GB, requesting 3GB",
})

# 17. refuel_data with gb_amount <= 2, active line — PASS
TEST_CASES.append({
    "id": 17,
    "domain": "telecom",
    "tool_name": "refuel_data",
    "tool_args": {"customer_id": "C1001", "line_id": "L1001", "gb_amount": 1.0},
    "user_instructions": "You are John Smith (555-123-2002). You want to add 1GB of data to line L1001.",
    "conversation": make_convo("Can you add 1GB of data to my line L1001 please?"),
    "expected": "pass",
    "reason": "Valid: 1GB <= 2GB max, line is active",
})

# 18. send_payment_request on a non-overdue bill — BLOCK
# Check bill statuses
bills = {b.bill_id: b for b in telecom_db.bills}
non_overdue_bill = None
for bid, b in bills.items():
    if b.status.value != "Overdue":
        non_overdue_bill = bid
        break
if non_overdue_bill:
    # Find which customer owns this bill
    bill_customer = None
    for c in telecom_db.customers:
        if non_overdue_bill in c.bill_ids:
            bill_customer = c.customer_id
            break
    TEST_CASES.append({
        "id": 18,
        "domain": "telecom",
        "tool_name": "send_payment_request",
        "tool_args": {"customer_id": bill_customer or "C1001", "bill_id": non_overdue_bill},
        "user_instructions": f"You want to pay bill {non_overdue_bill}.",
        "conversation": make_convo(f"I need to pay my bill {non_overdue_bill}."),
        "expected": "block",
        "reason": f"Bill {non_overdue_bill} is not overdue",
    })
else:
    TEST_CASES.append({
        "id": 18,
        "domain": "telecom",
        "tool_name": "send_payment_request",
        "tool_args": {"customer_id": "C1001", "bill_id": "B1001"},
        "user_instructions": "You want to pay bill B1001.",
        "conversation": make_convo("Pay my bill B1001."),
        "expected": "block_or_pass",
        "reason": "Depends on bill status",
    })

# 19. _check_tool_args: refuel with WRONG line_id — BLOCK (SLM)
TEST_CASES.append({
    "id": 19,
    "domain": "telecom",
    "tool_name": "refuel_data",
    "tool_args": {"customer_id": "C1001", "line_id": "L9999", "gb_amount": 1.0},
    "user_instructions": "You are John Smith (555-123-2002). You want to add data to line L1001.",
    "conversation": make_convo("Please add 1GB data to my line L1001."),
    "expected": "block",
    "reason": "_check_tool_args: line_id L9999 doesn't match user mention of L1001",
})

# 20. _check_tool_args: refuel with CORRECT line_id — PASS
TEST_CASES.append({
    "id": 20,
    "domain": "telecom",
    "tool_name": "refuel_data",
    "tool_args": {"customer_id": "C1001", "line_id": "L1001", "gb_amount": 2.0},
    "user_instructions": "You are John Smith (555-123-2002). You want to add 2GB of data to line L1001.",
    "conversation": make_convo("Add 2GB data to my line L1001 please."),
    "expected": "pass",
    "reason": "Correct IDs + valid amount (2GB = max allowed)",
})


# ── Run tests ──────────────────────────────────────────────────────────────
def run_tests():
    # Create verifiers for each domain
    verifiers = {
        "airline": PolicyVerifier(db=airline_db, domain="airline", cheap_only=False),
        "retail": PolicyVerifier(db=retail_db, domain="retail", cheap_only=False),
        "telecom": PolicyVerifier(db=telecom_db, domain="telecom", cheap_only=False),
    }

    results = []
    correct = 0
    total = 0
    total_strict = 0  # excluding block_or_pass

    print(f"\n{'='*80}", flush=True)
    print(f"VERIFIER ACCURACY TEST — {len(TEST_CASES)} test cases", flush=True)
    print(f"{'='*80}\n", flush=True)

    for tc in TEST_CASES:
        domain = tc["domain"]
        v = verifiers[domain]
        v.reset()  # Fresh state per test
        v.set_user_instructions(tc["user_instructions"])

        # Classify task (needed for SLM-based checks)
        v.classify_task(tc["conversation"])

        result = v.verify(
            tool_name=tc["tool_name"],
            tool_args=tc["tool_args"],
            conversation=tc["conversation"],
        )

        blocked = result is not None
        expected = tc["expected"]

        if expected == "block":
            match = blocked
        elif expected == "pass":
            match = not blocked
        else:  # block_or_pass — either is acceptable
            match = True

        icon = "✓" if match else "✗"
        total += 1
        if expected != "block_or_pass":
            total_strict += 1
        if match:
            correct += 1

        outcome = "BLOCKED" if blocked else "PASSED"
        expected_str = expected.upper()

        print(f"  [{icon}] Test {tc['id']:2d} ({domain:8s}) {tc['tool_name']:35s} "
              f"Expected: {expected_str:12s} Got: {outcome:7s}", flush=True)
        if not match:
            print(f"      Reason: {tc['reason']}", flush=True)
            if result:
                print(f"      Verifier msg: {result[:150]}", flush=True)
        results.append({
            "id": tc["id"],
            "domain": domain,
            "tool": tc["tool_name"],
            "expected": expected,
            "got": "block" if blocked else "pass",
            "correct": match,
            "verifier_msg": result[:200] if result else None,
            "reason": tc["reason"],
        })

    print(f"\n{'='*80}")
    strict_correct = sum(1 for r in results if r["correct"] and r["expected"] != "block_or_pass")
    print(f"ACCURACY: {correct}/{total} ({100*correct/total:.1f}%)")
    if total_strict > 0:
        print(f"STRICT ACCURACY (excl block_or_pass): {strict_correct}/{total_strict} ({100*strict_correct/total_strict:.1f}%)")

    # Breakdown by domain
    for dom in ["airline", "retail", "telecom"]:
        dom_results = [r for r in results if r["domain"] == dom]
        dom_correct = sum(1 for r in dom_results if r["correct"])
        print(f"  {dom:8s}: {dom_correct}/{len(dom_results)}")

    # Breakdown: policy rules vs _check_tool_args
    arg_check_ids = {7, 8, 14, 15, 19, 20}
    policy_results = [r for r in results if r["id"] not in arg_check_ids]
    arg_results = [r for r in results if r["id"] in arg_check_ids]
    pc = sum(1 for r in policy_results if r["correct"])
    ac = sum(1 for r in arg_results if r["correct"])
    print(f"\n  Policy rules: {pc}/{len(policy_results)}")
    print(f"  _check_tool_args (SLM ID): {ac}/{len(arg_results)}")

    # Show failures
    failures = [r for r in results if not r["correct"]]
    if failures:
        print(f"\n{'='*80}")
        print("FAILURES:")
        for f in failures:
            print(f"  Test {f['id']} ({f['domain']}/{f['tool']}): expected {f['expected']}, got {f['got']}")
            print(f"    Reason: {f['reason']}")
            if f["verifier_msg"]:
                print(f"    Verifier: {f['verifier_msg']}")

    print()
    return results


if __name__ == "__main__":
    run_tests()
