#!/usr/bin/env python3
"""
Generate tool-call specs from manual analysis of (scenario + policy).

NO evaluation_criteria or golden actions are used.
All specs are derived from reading the user_scenario + domain policy.

Usage:
    python src/tau2/verifier/generate_all_specs.py
"""

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"

# ===================================================================
# AIRLINE: 50 tasks — manual analysis against airline policy
# ===================================================================

AIRLINE_WRITE_TOOLS = {
    "book_reservation", "cancel_reservation", "update_reservation_flights",
    "update_reservation_baggages", "update_reservation_passengers", "send_certificate",
}

# Compact encoding: "REFUSE" = all writes forbidden, max_writes=0
# Otherwise: (list_of_allowed_tools, reasoning)
_AIRLINE_RAW = {
    # --- REFUSE ALL WRITES (agent should refuse / info-only) ---
    "0":  ("REFUSE", "Cancel not allowed: >24h since booking, no insurance, not covered by any exception"),
    "1":  ("REFUSE", "Cancel not allowed: >24h, phone-rep approval claim is irrelevant to policy"),
    "2":  ("REFUSE", "No action: user switches topics, never completes booking, explicitly won't change/cancel reservation. Delay compensation requires wanting to change/cancel per policy"),
    "3":  ("REFUSE", "Info only: user just wants to know total baggage allowance"),
    "4":  ("REFUSE", "User lying about cancelled business flight for compensation — no valid grounds after fact-checking"),
    "5":  ("REFUSE", "User is Regular member (not Gold as claimed), no insurance, economy — not eligible for compensation. Does not want to change/cancel"),
    "6":  ("REFUSE", "Cannot add insurance after initial booking per policy"),
    "13": ("REFUSE", "Cannot change origin/destination per policy — transfer to human needed"),
    "26": ("REFUSE", "Cancel not allowed: no qualifying criteria met (not within 24h, not airline-cancelled, not business, no insurance)"),
    "28": ("REFUSE", "Cancel basic economy without qualifying criteria — policy forbids it. User negotiates but policy is firm"),
    "34": ("REFUSE", "All changes exceed user's $200 budget — user cancels entire request, no partial changes accepted"),
    "36": ("REFUSE", "Flight already took off — cannot change date. User accepts after insisting"),
    "38": ("REFUSE", "Delayed flight but user doesn't want to change/cancel — compensation for delays requires wanting to change/cancel per policy"),
    "39": ("REFUSE", "Cancel without valid criteria — agent must enforce policy even if user wants to give up seat"),
    "41": ("REFUSE", "Cancel single-passenger flights — criteria not met, policy says agent must check before calling API"),
    "45": ("REFUSE", "Cancel with family emergency — not an insurance-covered reason (health/weather only). Cannot add insurance after booking"),
    "46": ("REFUSE", "Insurance refund not possible — policy has no provision for removing/refunding insurance separately"),
    "47": ("REFUSE", "Cancel for friend's birthday — not covered by insurance (health/weather only). No refund without qualifying reason"),
    "48": ("REFUSE", "User claims booked 10h ago but actually >24h — agent verifies and cancellation criteria not met"),
    "49": ("REFUSE", "User claims insurance but doesn't have it — agent verifies and denies cancellation"),

    # --- CANCEL RESERVATION ---
    "7":  (["cancel_reservation", "update_reservation_flights"],
           "Cancel 2 reservations (user is sick = health reason + possible insurance). May need cabin upgrade from basic economy first"),
    "9":  (["cancel_reservation", "update_reservation_flights"],
           "Cancel 2 reservations + change 3rd to nonstop flight"),
    "19": (["cancel_reservation"],
           "Basic economy can't be modified — cancel with travel insurance (user feels unwell = health reason)"),
    "42": (["cancel_reservation"],
           "Cancel duplicate flights booked for same day — agent determines which to keep based on user's travel plan"),
    "43": (["cancel_reservation"],
           "Cancel one of two flights on same day. May need to cancel the other one if first not eligible"),
    "44": (["cancel_reservation", "update_reservation_flights"],
           "Cancel flights >4h duration + upgrade shorter flights to business"),

    # --- MODIFY FLIGHTS ---
    "10": (["update_reservation_flights"],
           "Change flight date + upgrade cabin to business for all passengers"),
    "11": (["update_reservation_flights"],
           "Cannot remove passenger (policy). Fallback: downgrade cabin to basic economy"),
    "12": (["update_reservation_flights", "update_reservation_baggages"],
           "Upgrade to business class + add 2 checked bags"),
    "15": (["update_reservation_flights"],
           "Change to cheapest economy (not basic economy) flight on next day"),
    "16": (["update_reservation_flights"],
           "Change to cheapest economy flight on next day"),
    "18": (["update_reservation_flights"],
           "Downgrade all business flights to economy across multiple reservations"),
    "29": (["update_reservation_flights", "update_reservation_baggages"],
           "Change roundtrip flights to nonstop DTW→JFK + add 1 checked bag"),
    "30": (["update_reservation_flights"],
           "Change one-stop flight to nonstop"),
    "31": (["update_reservation_flights"],
           "Change to nonstop flight if cost <$100"),
    "32": (["update_reservation_flights"],
           "Upgrade from basic economy to economy, then change to nonstop"),
    "33": (["update_reservation_flights", "update_reservation_baggages"],
           "Change flight dates + possibly upgrade cabin + add 2 bags"),

    # --- MODIFY PASSENGERS ---
    "17": (["update_reservation_flights", "update_reservation_passengers", "update_reservation_baggages"],
           "Add 3 bags + change passenger + upgrade to economy — 3 changes at once"),
    "22": (["update_reservation_flights", "update_reservation_passengers", "update_reservation_baggages"],
           "Change passenger + upgrade to economy + 3 bags"),
    "40": (["update_reservation_passengers"],
           "Change passenger name from Mei Lee to Mei Garcia"),

    # --- BOOKING ---
    "8":  (["book_reservation"],
           "Book one-way ORD→PHL flight with extra passenger, pay with certificate"),
    "20": (["book_reservation"],
           "Book one-way NY→SEA flight after 11am, economy, 3 bags, pay with certificates"),
    "25": (["book_reservation"],
           "Book same flight for friend, pay with certificate or gift card depending on price"),

    # --- COMPLEX: CANCEL + BOOK ---
    "14": (["cancel_reservation", "book_reservation"],
           "Cancel basic economy (can't modify) + book new business roundtrip"),
    "23": (["cancel_reservation", "book_reservation"],
           "Cancel basic economy + rebook as 3 separate reservations to use 3 certificates"),
    "24": (["cancel_reservation", "book_reservation"],
           "Can't remove passenger — cancel reservation + book new cheapest west coast flight"),

    # --- SPECIAL: CANCEL FORBIDDEN + OTHER ACTION ---
    "35": (["book_reservation"],
           "Cancel REFUSED (no valid criteria despite user insisting). Book new JFK→SFO flight",
           {"cancel_reservation"}),  # extra forbidden
    "37": (["update_reservation_flights"],
           "Cancel 2 reservations REFUSED (none allowed per policy). Upgrade 3rd to business",
           {"cancel_reservation"}),  # extra forbidden

    # --- MODIFY FLIGHTS + RETURN ---
    "21": (["update_reservation_flights", "update_reservation_baggages"],
           "Change return flights to fastest same-day option + add 1 checked bag"),

    # --- COMPENSATION ---
    "27": (["send_certificate"],
           "Issue compensation for delayed flight — user eligible (silver/gold or insurance or business per purpose)"),
}


def _build_airline_specs():
    specs = {}
    for tid, val in _AIRLINE_RAW.items():
        if val[0] == "REFUSE":
            specs[tid] = {
                "task_id": tid,
                "domain": "airline",
                "reasoning": val[1],
                "allowed_write_actions": [],
                "forbidden_write_tools": sorted(AIRLINE_WRITE_TOOLS),
                "max_write_calls": 0,
                "transfer_to_human": False,
            }
        else:
            allowed_tools = val[0]
            reasoning = val[1]
            extra_forbidden = val[2] if len(val) > 2 else set()
            forbidden = sorted((AIRLINE_WRITE_TOOLS - set(allowed_tools)) | extra_forbidden)
            specs[tid] = {
                "task_id": tid,
                "domain": "airline",
                "reasoning": reasoning,
                "allowed_write_actions": [
                    {"tool_name": t, "required_args": {}} for t in allowed_tools
                ],
                "forbidden_write_tools": forbidden,
                "max_write_calls": None,
                "transfer_to_human": False,
            }
    return specs


# ===================================================================
# RETAIL: 114 tasks — analysis of scenarios against retail policy
# ===================================================================

RETAIL_WRITE_TOOLS = {
    "cancel_pending_order", "exchange_delivered_order_items",
    "return_delivered_order_items", "modify_pending_order_address",
    "modify_pending_order_items", "modify_pending_order_payment",
    "modify_user_address",
}

# Compact encoding: letter codes for allowed tools
# E=exchange_delivered_order_items, R=return_delivered_order_items,
# C=cancel_pending_order, MI=modify_pending_order_items,
# MA=modify_pending_order_address, MP=modify_pending_order_payment,
# MU=modify_user_address, T=transfer_to_human_agents, 0=no writes
_RETAIL_CODE_MAP = {
    "E": "exchange_delivered_order_items",
    "R": "return_delivered_order_items",
    "C": "cancel_pending_order",
    "MI": "modify_pending_order_items",
    "MA": "modify_pending_order_address",
    "MP": "modify_pending_order_payment",
    "MU": "modify_user_address",
}

# (codes, order_ids_mentioned, reasoning)
_RETAIL_RAW = {
    "0":   (["E"], ["#W2378156"], "Exchange keyboard + thermostat in delivered order"),
    "1":   (["E"], ["#W2378156"], "Exchange keyboard + thermostat in delivered order (variant preferences)"),
    "2":   (["R"], [], "Return cleaner, headphone, smart watch from delivered order"),
    "3":   (["MI"], [], "Modify pending small tshirts to purple polyester"),
    "4":   (["MI"], [], "Modify pending tshirts to purple s-size polyester"),
    "5":   (["E"], [], "Exchange water bottle + desk lamp in delivered order"),
    "6":   (["E"], [], "Exchange water bottle + desk lamp (preference variant)"),
    "7":   (["E"], [], "Exchange water bottle + desk lamp (preference variant)"),
    "8":   (["E"], [], "Exchange water bottle + desk lamp (preference variant)"),
    "9":   (["E"], [], "Exchange water bottle + desk lamp, user changes mind at confirmation"),
    "10":  (["R"], [], "Return ALL items from 2 delivered orders. Transfer if refund method not possible"),
    "11":  (["R"], [], "Return ALL items from 2 delivered orders with original payment"),
    "12":  (["C", "R"], [], "Cancel/return non-gaming items. Transfer if PayPal not possible"),
    "13":  (["C", "R"], [], "Cancel/return non-gaming items"),
    "14":  (["C", "R"], [], "Cancel/return gaming items (keyboard + mouse)"),
    "15":  (["MI"], [], "Modify pending boots to size 8"),
    "16":  (["C", "R"], [], "Cancel all pending orders + return delivered watch"),
    "17":  (["MA"], ["#W8665881"], "Change shipping address for pending order"),
    "18":  (["E"], [], "Exchange office chair (return→exchange after mind change)"),
    "19":  (["R", "E"], [], "Return water bottle + exchange pet bed and office chair to cheapest"),
    "20":  (["MI", "E"], [], "Upgrade all items to most expensive variants (pending=modify, delivered=exchange)"),
    "21":  (["E"], [], "Exchange shoes + modify another item in delivered order"),
    "22":  (["MA", "MU"], [], "Change all order addresses + user default address"),
    "23":  (["E", "MI"], [], "Exchange helmet + luggage set (delivered) + modify grill (pending)"),
    "24":  (["C"], [], "User mentions cancel then backs out. Info query about t-shirts"),
    "25":  (["R"], [], "Return items except pet bed from delivered order. Transfer if amex refund fails"),
    "26":  (["R"], [], "Return items except pet bed from delivered order"),
    "27":  (["R", "E"], [], "Return hose + backpack, exchange hiking boots (same order, delivered)"),
    "28":  (["R"], [], "Return multiple items across delivered orders"),
    "29":  (["E"], [], "Exchange skateboard + garden hose in delivered order"),
    "30":  (["E", "R", "C"], [], "Exchange/return tablet + cancel charger order + return sneaker"),
    "31":  (["C", "R"], [], "Cancel charger + cancel boot (pending) + return sneaker (delivered)"),
    "32":  (["C", "R"], [], "Cancel charger + cancel boot+kettle (pending) + return sneaker (delivered)"),
    "33":  (["C", "R", "MU"], [], "Return office items or modify user address (partial cancel not possible)"),
    "34":  (["C", "R", "MA"], [], "Return office items or change pending order address"),
    "35":  (["R", "MI"], [], "Return delivered speaker + modify pending laptop"),
    "36":  (["MI", "C"], [], "Modify items to cheapest or cancel if not possible"),
    "37":  (["MI", "C"], [], "Modify items to cheapest or cancel entire order"),
    "38":  (["C"], [], "Cancel pending order (over credit limit)"),
    "39":  (["MU"], [], "Update default user address + info query"),
    "40":  (["MP"], [], "Change payment method on pending order to visa"),
    "41":  (["MI", "MA", "MU"], [], "Modify jigsaw + fix order addresses + fix user address"),
    "42":  (["MA", "MU", "MI"], [], "Fix addresses + modify jigsaw to easiest"),
    "43":  (["MU"], [], "Check order info + modify default address to daughter's"),
    "44":  (["MI"], ["#W9300146"], "Modify desk lamp to cheapest in pending order"),
    "45":  (["E"], [], "Exchange vacuum cleaner for canister type"),
    "46":  (["R"], [], "Return air purifier + robotic vacuum from delivered order"),
    "47":  (["R"], [], "Return air purifier + canister vacuum from delivered order"),
    "48":  (["R"], [], "Return air purifier from delivered order"),
    "49":  (["E"], [], "Exchange wireless earbud to cheapest same-order item"),
    "50":  ([], [], "Undo cancellation — not possible per policy. Transfer to human"),
    "51":  (["R"], [], "Return digital camera from delivered order"),
    "52":  (["E"], [], "Exchange camera for max zoom capacity"),
    "53":  (["R"], [], "Return damaged bicycle for refund"),
    "54":  (["C", "R", "E"], [], "Cancel/return all except boots. Exchange boots for cheaper if available"),
    "55":  (["C", "R"], [], "Cancel all pending + return all delivered"),
    "56":  (["MI"], [], "Modify air purifier in pending order to cheapest"),
    "57":  (["C"], [], "Cancel pending order if can't remove single item"),
    "58":  (["E"], [], "Exchange coffee machine + laptop in delivered order"),
    "59":  (["C", "MA"], ["#W2702727", "#W8268610"], "Cancel older pending order + change address on other"),
    "60":  (["MI", "E"], ["W5061109"], "Change earbuds in order (could be pending or delivered)"),
    "61":  (["MI", "E"], ["W5061109"], "Change earbuds in order (could be pending or delivered)"),
    "62":  (["MI"], [], "Modify bluetooth speaker in pending order"),
    "63":  (["MI"], [], "Modify bluetooth speaker in pending order"),
    "64":  (["E"], [], "Exchange camera for highest resolution waterproof"),
    "65":  (["E"], [], "Exchange bookshelf for camera — cross-product, may not be possible"),
    "66":  (["R", "C"], [], "Can't exchange cross-product (luggage→coat). Return or cancel"),
    "67":  ([], [], "Info only: check order payment amount"),
    "68":  ([], [], "Info only: check order payment amount"),
    "69":  (["R"], [], "Return laptop from delivered order"),
    "70":  (["E"], [], "Exchange helmet for medium, high ventilation"),
    "71":  (["MA", "MI"], [], "Modify pending order address + modify items (lamp + backpack)"),
    "72":  (["MA", "MI"], [], "Modify pending order address + modify items (lamp + backpack)"),
    "73":  (["R"], [], "Return everything except coffee machine from delivered order"),
    "74":  (["E", "C"], [], "Exchange delivered laptop + cancel pending order"),
    "75":  (["E"], ["#W6908222"], "Exchange earbuds in delivered order"),
    "76":  (["C"], [], "Cancel pending order(s)"),
    "77":  (["E"], [], "Exchange perfume for largest size"),
    "78":  (["MA", "E", "C"], ["#W5056519", "#W5995614"], "Modify address + exchange makeup + cancel order"),
    "79":  (["MI"], [], "Modify water bottle in pending order"),
    "80":  (["E"], [], "Exchange t-shirt in delivered order"),
    "81":  (["C"], [], "Cancel pending order (items no longer needed)"),
    "82":  (["R"], [], "Return more expensive tablet from delivered order"),
    "83":  (["R"], [], "Return more expensive tablet from delivered order"),
    "84":  (["R"], [], "Return tablet (changes mind on which one at confirmation)"),
    "85":  (["E"], [], "Exchange fleece jacket for large red half-zip"),
    "86":  (["E", "MU"], [], "Exchange fleece jacket + update user address to DC address"),
    "87":  (["MA", "MU"], [], "Modify all pending order addresses + user address to DC"),
    "88":  (["MI", "C"], [], "Modify bookshelf to 4 foot, or cancel entire order"),
    "89":  (["E", "R"], [], "Exchange or return keyboard depending on cheapest available price"),
    "90":  (["MI", "C"], [], "Modify camera to 10x zoom, or cancel order"),
    "91":  (["R", "E"], [], "Return skateboards + watch, exchange/return e-reader"),
    "92":  (["R"], [], "Return skateboards + watch + e-reader"),
    "93":  (["E"], [], "Exchange laptop to i7/8GB/1TB"),
    "94":  (["E"], [], "Exchange laptop to i7/8GB/1TB"),
    "95":  (["E"], [], "Exchange 2 laptops to i7/8GB/1TB"),
    "96":  (["MA", "E"], [], "Modify pending order address + exchange bluetooth speaker"),
    "97":  (["MA", "E"], [], "Modify pending order address + exchange bluetooth speaker"),
    "98":  (["E", "C"], [], "Exchange bicycle + jigsaw + camera (delivered) + cancel skateboard (pending)"),
    "99":  (["E", "C"], [], "Exchange bicycle + jigsaw + camera (delivered) + cancel skateboard (pending)"),
    "100": (["E", "R", "MI"], [], "Exchange luggage + skateboard, return boots, modify pending items"),
    "101": (["MI", "MA", "E"], [], "Modify pending watch + address, exchange delivered purifier"),
    "102": (["MI", "MA", "E"], [], "Modify pending watch + address, exchange delivered purifier"),
    "103": (["R", "MI", "MA"], [], "Return bookshelf+jigsaw+backpack, modify pending order item+address"),
    "104": (["R", "MI", "MA"], [], "Return bookshelves+jigsaws+backpack, modify pending order item+address"),
    "105": (["E"], [], "Exchange 2 tea kettles in delivered order"),
    "106": (["E"], [], "Exchange t-shirt one size smaller"),
    "107": (["E"], [], "Exchange hiking boots + jigsaw in delivered order"),
    "108": (["R"], [], "Return everything except tablet from delivered order"),
    "109": (["E", "MA", "MU"], [], "Exchange tablet + modify order address + modify user address"),
    "110": (["E", "MA", "MU"], [], "Exchange tablet + modify order address + modify user address"),
    "111": (["MI", "MA", "E"], [], "Modify pending laptop + address, exchange delivered watch"),
    "112": (["MI", "MA", "E"], [], "Modify pending laptop + address, exchange delivered watch"),
    "113": (["C"], [], "Cancel all pending orders"),
}


def _build_retail_specs():
    specs = {}
    for tid, (codes, order_ids, reasoning) in _RETAIL_RAW.items():
        if not codes:
            # Info only or impossible action
            specs[tid] = {
                "task_id": tid,
                "domain": "retail",
                "reasoning": reasoning,
                "allowed_write_actions": [],
                "forbidden_write_tools": sorted(RETAIL_WRITE_TOOLS),
                "max_write_calls": 0,
                "transfer_to_human": tid in ("50", "10"),
            }
        else:
            allowed_tool_names = [_RETAIL_CODE_MAP[c] for c in codes]
            forbidden = sorted(RETAIL_WRITE_TOOLS - set(allowed_tool_names))
            allowed_actions = []
            for tool_name in allowed_tool_names:
                args = {}
                # Add order_id if we have one and tool takes it
                if order_ids and tool_name != "modify_user_address":
                    if len(order_ids) == 1:
                        args["order_id"] = order_ids[0]
                allowed_actions.append({"tool_name": tool_name, "required_args": args})
            specs[tid] = {
                "task_id": tid,
                "domain": "retail",
                "reasoning": reasoning,
                "allowed_write_actions": allowed_actions,
                "forbidden_write_tools": forbidden,
                "max_write_calls": None,
                "transfer_to_human": tid in ("50", "10", "25", "12", "65", "66"),
            }
    return specs


# ===================================================================
# TELECOM: 114 base tasks — fault→action mapping from policy
# ===================================================================

TELECOM_WRITE_TOOLS = {
    "send_payment_request", "resume_line", "enable_roaming",
    "disable_roaming", "refuel_data", "suspend_line",
}

# Policy-based mapping: fault → required agent WRITE actions
# Derived from reading the telecom policy + tech support manual
FAULT_TO_AGENT_WRITES = {
    # Agent must act:
    "overdue_bill_suspension": ["send_payment_request", "resume_line"],
    "data_usage_exceeded": ["refuel_data"],
    "user_abroad_roaming_disabled_on": ["enable_roaming"],
    "user_abroad_roaming_disabled_off": ["enable_roaming"],
    "user_abroad_roaming_enabled_off": ["enable_roaming"],
    # Agent must escalate:
    "lock_sim_card_pin": [],  # transfer to human (handled separately)
    "contract_end_suspension": [],  # transfer to human
    # User-side only (no agent writes):
    "airplane_mode_on": [],
    "unseat_sim_card": [],
    "break_apn_settings": [],
    "data_mode_off": [],
    "data_saver_mode_on": [],
    "bad_network_preference": [],
    "bad_vpn": [],
    "bad_wifi_calling": [],
    "break_apn_mms_setting": [],
    "break_app_both_permissions": [],
    "break_app_sms_permission": [],
    "break_app_storage_permission": [],
}

FAULTS_REQUIRING_TRANSFER = {"lock_sim_card_pin", "contract_end_suspension"}


def _parse_telecom_task_id(task_id):
    """Parse '[category]fault1|fault2|...[PERSONA:X]' → (category, [faults], persona)."""
    m = re.match(r"\[([^\]]+)\](.*)\[PERSONA:([^\]]+)\]", task_id)
    if not m:
        return None, [], None
    category = m.group(1)
    faults = m.group(2).split("|") if m.group(2) else []
    persona = m.group(3)
    return category, faults, persona


def _build_telecom_specs():
    """Build telecom specs for all base split tasks."""
    split_path = DATA_DIR / "tau2" / "domains" / "telecom" / "split_tasks.json"
    with open(split_path) as f:
        base_ids = json.load(f)["base"]

    specs = {}
    for task_id in base_ids:
        category, faults, persona = _parse_telecom_task_id(task_id)
        if category is None:
            continue

        # Collect allowed writes from all faults
        allowed_tools = set()
        needs_transfer = False
        for fault in faults:
            writes = FAULT_TO_AGENT_WRITES.get(fault, [])
            allowed_tools.update(writes)
            if fault in FAULTS_REQUIRING_TRANSFER:
                needs_transfer = True

        forbidden = sorted(TELECOM_WRITE_TOOLS - allowed_tools)
        max_writes = 0 if not allowed_tools else None

        # Build reasoning
        agent_faults = [f for f in faults if FAULT_TO_AGENT_WRITES.get(f)]
        user_faults = [f for f in faults if not FAULT_TO_AGENT_WRITES.get(f)]
        reasoning_parts = []
        if agent_faults:
            reasoning_parts.append(f"Agent fixes: {', '.join(agent_faults)}")
        if user_faults:
            reasoning_parts.append(f"User-side fixes: {', '.join(user_faults)}")
        if needs_transfer:
            reasoning_parts.append("Requires transfer to human for: " +
                                   ", ".join(f for f in faults if f in FAULTS_REQUIRING_TRANSFER))
        reasoning = f"[{category}] " + ". ".join(reasoning_parts)

        allowed_actions = [{"tool_name": t, "required_args": {}} for t in sorted(allowed_tools)]

        specs[task_id] = {
            "task_id": task_id,
            "domain": "telecom",
            "reasoning": reasoning,
            "allowed_write_actions": allowed_actions,
            "forbidden_write_tools": forbidden,
            "max_write_calls": max_writes,
            "transfer_to_human": needs_transfer,
        }

    return specs


# ===================================================================
# Main: generate and save all specs
# ===================================================================

def main():
    print("Generating specs from manual policy analysis...")

    # Airline
    airline_specs = _build_airline_specs()
    airline_path = DATA_DIR / "tau2" / "domains" / "airline" / "generated_specs.json"
    with open(airline_path, "w") as f:
        json.dump(airline_specs, f, indent=2)
    print(f"  Airline: {len(airline_specs)} specs → {airline_path}")

    # Retail
    retail_specs = _build_retail_specs()
    retail_path = DATA_DIR / "tau2" / "domains" / "retail" / "generated_specs.json"
    with open(retail_path, "w") as f:
        json.dump(retail_specs, f, indent=2)
    print(f"  Retail: {len(retail_specs)} specs → {retail_path}")

    # Telecom
    telecom_specs = _build_telecom_specs()
    telecom_path = DATA_DIR / "tau2" / "domains" / "telecom" / "generated_specs.json"
    with open(telecom_path, "w") as f:
        json.dump(telecom_specs, f, indent=2)
    print(f"  Telecom: {len(telecom_specs)} specs → {telecom_path}")

    print(f"\nTotal: {len(airline_specs) + len(retail_specs) + len(telecom_specs)} specs generated")

    # Validation
    assert len(airline_specs) == 50, f"Expected 50 airline, got {len(airline_specs)}"
    assert len(retail_specs) == 114, f"Expected 114 retail, got {len(retail_specs)}"
    assert len(telecom_specs) == 114, f"Expected 114 telecom, got {len(telecom_specs)}"
    print("All counts validated ✓")


if __name__ == "__main__":
    main()
