"""
Detailed airline specs with argument-level validation.

Each spec is derived from:
  - The user scenario (what info the user provides to the agent)
  - The airline policy (rules the agent must follow)

We do NOT use evaluation_criteria/ground truth. Instead we encode:
  - Which reservation IDs the user mentions → required_reads
  - Which WRITE operations are consistent with the scenario + policy
  - Which operations are forbidden by policy for this scenario
  - Argument constraints (reservation_id, cabin, etc.) from user-stated info
"""

from tau2.verifier.spec import ActionConstraint, TaskSpec


def _refuse_all(task_id: str, description: str) -> TaskSpec:
    """Helper for tasks where the agent should refuse ALL write operations."""
    return TaskSpec(
        task_id=task_id,
        description=description,
        forbidden_write_tools={
            "book_reservation",
            "cancel_reservation",
            "update_reservation_flights",
            "update_reservation_baggages",
            "update_reservation_passengers",
            "send_certificate",
        },
        max_write_calls=0,
    )


def _no_cancel_no_modify(task_id: str, description: str, allow_transfer: bool = True) -> TaskSpec:
    """Helper for tasks where agent should not cancel or modify."""
    forbidden = {
        "cancel_reservation",
        "update_reservation_flights",
        "update_reservation_baggages",
        "update_reservation_passengers",
        "book_reservation",
        "send_certificate",
    }
    return TaskSpec(
        task_id=task_id,
        description=description,
        forbidden_write_tools=forbidden,
        max_write_calls=1 if allow_transfer else 0,
        allowed_write_actions=[
            ActionConstraint(tool_name="transfer_to_human_agents")
        ] if allow_transfer else [],
    )


# ============================================================================
# All 50 airline task specs
# ============================================================================

_SPECS: dict[str, TaskSpec] = {}


# --- TASK 0: Refuse cancellation (no insurance, >24h, no valid exception) ---
_SPECS["0"] = _refuse_all(
    "0",
    "User wants to cancel reservation EHGLP3 but >24h since booking, no insurance, "
    "no valid policy exception. Agent must refuse all write operations.",
)
_SPECS["0"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "EHGLP3"}),
]


# --- TASK 1: Refuse cancellation (basic economy, no insurance, >24h) ---
_SPECS["1"] = TaskSpec(
    task_id="1",
    description="User wants to cancel PHL→LGA trip. Basic economy, no insurance, >24h. "
    "Agent should not approve cancellation.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "book_reservation", "send_certificate",
    },
    max_write_calls=0,
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "raj_sanchez_7340"}),
    ],
)


# --- TASK 2: No compensation, no cancel/modify ---
_SPECS["2"] = TaskSpec(
    task_id="2",
    description="User brings up delayed flight but does NOT want to cancel or modify. "
    "Agent should not offer compensation unless user asks. "
    "Agent should not offer $50 certificate.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "book_reservation", "send_certificate",
    },
    max_write_calls=0,
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "noah_muller_9847"}),
    ],
)


# --- TASK 3: Info only, transfer if user insists on Gold ---
_SPECS["3"] = TaskSpec(
    task_id="3",
    description="User wants baggage count info for reservation JMO1MG. "
    "User is Silver (not Gold). May request transfer to supervisor.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "book_reservation", "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(tool_name="transfer_to_human_agents"),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "JMO1MG"}),
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "anya_garcia_5901"}),
    ],
)


# --- TASK 4: No compensation (user fabricating story) ---
_SPECS["4"] = _refuse_all(
    "4",
    "User claims business flight was cancelled causing missed meeting, but flight was "
    "NOT cancelled and was NOT business class. Agent must not offer any compensation.",
)
_SPECS["4"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_user_details", required_args={"user_id": "sophia_silva_7557"}),
]


# --- TASK 5: Delayed flight complaint, no compensation (user doesn't want cancel/modify) ---
_SPECS["5"] = TaskSpec(
    task_id="5",
    description="User complains about delayed flight HAT045. Claims Gold member but is Regular. "
    "Does NOT want to cancel or modify flight. Agent should not offer compensation "
    "since user doesn't want to change/cancel.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "book_reservation", "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(tool_name="transfer_to_human_agents"),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "mei_brown_7075"}),
    ],
)


# --- TASK 6: Info only, no insurance addition allowed ---
_SPECS["6"] = _refuse_all(
    "6",
    "User asks about insurance on reservation PEP4E0. Insurance cannot be added after booking. "
    "User does NOT want transfer.",
)
_SPECS["6"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "PEP4E0"}),
]


# --- TASK 7: Upgrade XEHM4B to business then cancel both ---
_SPECS["7"] = TaskSpec(
    task_id="7",
    description="User wants to cancel reservations XEHM4B and 59XX6W. "
    "XEHM4B is basic economy → must upgrade to business first (CC ending 2135). "
    "User is sick (valid insurance reason). "
    "Correct sequence: upgrade XEHM4B → cancel XEHM4B → cancel 59XX6W.",
    forbidden_write_tools={
        "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "XEHM4B", "cabin": "business"},
            compare_args=["reservation_id", "cabin"],
            description="Upgrade XEHM4B to business class before cancellation",
        ),
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "XEHM4B"},
            description="Cancel reservation XEHM4B after upgrading to business",
        ),
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "59XX6W"},
            description="Cancel reservation 59XX6W (has insurance, user is sick)",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "XEHM4B"}),
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "59XX6W"}),
    ],
)


# --- TASK 8: Book one-way ORD→PHL economy ---
_SPECS["8"] = TaskSpec(
    task_id="8",
    description="User wants to book one-way ORD→PHL on May 26, economy, 2 passengers "
    "(Sophia Silva + Kevin Smith), no baggage, no insurance.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="book_reservation",
            required_args={
                "origin": "ORD", "destination": "PHL",
                "flight_type": "one_way", "cabin": "economy",
                "insurance": "no",
            },
            compare_args=["origin", "destination", "flight_type", "cabin", "insurance"],
            description="Book one-way ORD→PHL economy with no insurance",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "sophia_silva_7557"}),
    ],
)


# --- TASK 9: Agent should refuse both cancellations and not modify ---
_SPECS["9"] = _refuse_all(
    "9",
    "User wants to cancel IFOYYZ (basic economy, no insurance, >24h) and NQNU5R (already departed). "
    "Neither qualifies for cancellation. M20IZO change to nonstop is not possible. "
    "Agent should not perform any write operations.",
)


# --- TASK 10: No modification possible ---
_SPECS["10"] = _refuse_all(
    "10",
    "User wants to push back IAH→SEA flight and upgrade to business. "
    "Policy constraints make this not possible within user's budget. "
    "Agent should not make any changes.",
)


# --- TASK 11: Downgrade GV1N64 to basic economy ---
_SPECS["11"] = TaskSpec(
    task_id="11",
    description="User wants to remove passenger from GV1N64 (not allowed). "
    "Fallback: downgrade all to basic economy. Reservation GV1N64, LAS→DEN.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "GV1N64", "cabin": "basic_economy"},
            compare_args=["reservation_id", "cabin"],
            description="Downgrade GV1N64 to basic economy (cannot remove passenger)",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "james_patel_9828"}),
    ],
)


# --- TASK 12: Add 2 bags to YAX4DR (business upgrade too expensive) ---
_SPECS["12"] = TaskSpec(
    task_id="12",
    description="User wants to upgrade YAX4DR to business and add 2 bags. "
    "Business upgrade exceeds $650 budget. Cannot upgrade for only one passenger. "
    "Bags can be added for free (Gold member).",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_baggages",
            required_args={"reservation_id": "YAX4DR", "total_baggages": 2, "nonfree_baggages": 0},
            compare_args=["reservation_id", "total_baggages", "nonfree_baggages"],
            description="Add 2 free checked bags to YAX4DR",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "YAX4DR"}),
    ],
)


# --- TASK 13: Transfer to human (can't change origin/destination) ---
_SPECS["13"] = TaskSpec(
    task_id="13",
    description="User wants to change ATL→LAX to ATL→LAS in XEWRD9. "
    "Policy: cannot modify origin/destination. Must transfer to human.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_flights", "update_reservation_baggages",
        "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(tool_name="transfer_to_human_agents"),
    ],
)


# --- TASK 14: Cancel and rebook as business ---
_SPECS["14"] = TaskSpec(
    task_id="14",
    description="User wants to change basic economy reservation to business. "
    "Basic economy can't be modified → cancel K1NW8N and book new business RT JFK→SFO. "
    "Payment order: certificates → gift cards → Mastercard. "
    "Only if Mastercard < $2000.",
    forbidden_write_tools={
        "update_reservation_flights", "update_reservation_passengers",
        "update_reservation_baggages", "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "K1NW8N"},
            description="Cancel basic economy reservation K1NW8N",
        ),
        ActionConstraint(
            tool_name="book_reservation",
            required_args={
                "origin": "JFK", "destination": "SFO",
                "flight_type": "round_trip", "cabin": "business",
                "insurance": "no",
            },
            compare_args=["origin", "destination", "flight_type", "cabin", "insurance"],
            description="Book new business RT JFK→SFO with no insurance",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "mohamed_silva_9265"}),
    ],
)


# --- TASK 15: Update M05KNL to economy ---
_SPECS["15"] = TaskSpec(
    task_id="15",
    description="User wants to change ATL→PHL trip to cheapest economy on the day after original. "
    "EWR also acceptable. Reservation M05KNL.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "M05KNL", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
            description="Update M05KNL to economy class flights one day later",
        ),
    ],
)


# --- TASK 16: Same as 15 - Update M05KNL to economy ---
_SPECS["16"] = TaskSpec(
    task_id="16",
    description="User wants to change ATL→PHL trip to cheapest economy on the day after original. "
    "Reservation M05KNL.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "M05KNL", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
            description="Update M05KNL to economy on the day after original",
        ),
    ],
)


# --- TASK 17: Multiple changes to FQ8APE ---
_SPECS["17"] = TaskSpec(
    task_id="17",
    description="User wants to: upgrade FQ8APE to economy, change passenger to Omar Rossi, "
    "add 3 checked bags. All on reservation FQ8APE.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "FQ8APE", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
            description="Upgrade FQ8APE from basic economy to economy",
        ),
        ActionConstraint(
            tool_name="update_reservation_passengers",
            required_args={"reservation_id": "FQ8APE"},
            compare_args=["reservation_id"],
            description="Update passenger on FQ8APE to Omar Rossi",
        ),
        ActionConstraint(
            tool_name="update_reservation_baggages",
            required_args={"reservation_id": "FQ8APE", "total_baggages": 3, "nonfree_baggages": 0},
            compare_args=["reservation_id", "total_baggages", "nonfree_baggages"],
            description="Add 3 free checked bags to FQ8APE",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "omar_rossi_1241"}),
    ],
)


# --- TASK 18: Downgrade 5 reservations from business to economy ---
_SPECS["18"] = TaskSpec(
    task_id="18",
    description="User wants to downgrade ALL business reservations to economy. "
    "Reservations: JG7FMM, 2FBBAH, X7BYG1, EQ1G6C, BOH180. No other changes.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "JG7FMM", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
        ),
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "2FBBAH", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
        ),
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "X7BYG1", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
        ),
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "EQ1G6C", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
        ),
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "BOH180", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "omar_davis_3817"}),
    ],
)


# --- TASK 19: Cancel Z7GOZK (basic economy, has insurance, user is unwell) ---
_SPECS["19"] = TaskSpec(
    task_id="19",
    description="User wants to change return flight but basic economy can't be modified. "
    "Willing to cancel via insurance (feels unwell). Reservation Z7GOZK.",
    forbidden_write_tools={
        "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
        "update_reservation_flights",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "Z7GOZK"},
            description="Cancel Z7GOZK (has insurance, user feels unwell)",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "olivia_gonzalez_2305"}),
    ],
)


# --- TASK 20: Book one-way JFK→SEA economy ---
_SPECS["20"] = TaskSpec(
    task_id="20",
    description="User wants one-way NY→SEA on May 20. Economy, no flights before 11am EST. "
    "3 bags, no insurance. Payment: certificates + CC ending 7447.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="book_reservation",
            required_args={
                "destination": "SEA",
                "flight_type": "one_way", "cabin": "economy",
                "total_baggages": 3, "insurance": "no",
            },
            compare_args=["destination", "flight_type", "cabin", "total_baggages", "insurance"],
            description="Book one-way economy to SEA, 3 bags, no insurance",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "mia_li_3668"}),
    ],
)


# --- TASK 21: Update flights and baggages on OBUT9V ---
_SPECS["21"] = TaskSpec(
    task_id="21",
    description="User wants to change return flights in OBUT9V (Houston→Denver trip) "
    "to fastest return on May 27. Add 1 more checked bag. Economy. "
    "Use gift card with smallest balance.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "OBUT9V", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
            description="Update OBUT9V return flights to fastest economy option on May 27",
        ),
        ActionConstraint(
            tool_name="update_reservation_baggages",
            required_args={"reservation_id": "OBUT9V", "total_baggages": 2, "nonfree_baggages": 0},
            compare_args=["reservation_id", "total_baggages", "nonfree_baggages"],
            description="Add 1 more checked bag (total 2) to OBUT9V",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "sofia_kim_7287"}),
    ],
)


# --- TASK 22: Multiple changes to FQ8APE (same as 17 but different instructions) ---
_SPECS["22"] = TaskSpec(
    task_id="22",
    description="User wants to: upgrade FQ8APE to economy, change passenger to Omar Rossi, "
    "add 3 checked bags. All on reservation FQ8APE.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "FQ8APE", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
            description="Upgrade FQ8APE to economy",
        ),
        ActionConstraint(
            tool_name="update_reservation_passengers",
            required_args={"reservation_id": "FQ8APE"},
            compare_args=["reservation_id"],
            description="Change passenger to Omar Rossi",
        ),
        ActionConstraint(
            tool_name="update_reservation_baggages",
            required_args={"reservation_id": "FQ8APE", "total_baggages": 3, "nonfree_baggages": 0},
            compare_args=["reservation_id", "total_baggages", "nonfree_baggages"],
            description="Set 3 checked bags on FQ8APE",
        ),
    ],
)


# --- TASK 23: Cancel K1NW8N and book 3 separate reservations ---
_SPECS["23"] = TaskSpec(
    task_id="23",
    description="User wants to cancel K1NW8N (basic economy) and rebook as 3 separate "
    "business class reservations (one per passenger) JFK→SFO round trip. "
    "Payment order: certificates → gift cards → Mastercard.",
    forbidden_write_tools={
        "update_reservation_flights", "update_reservation_passengers",
        "update_reservation_baggages", "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "K1NW8N"},
            description="Cancel basic economy reservation K1NW8N",
        ),
        ActionConstraint(
            tool_name="book_reservation",
            required_args={
                "origin": "JFK", "destination": "SFO",
                "flight_type": "round_trip", "cabin": "business",
                "insurance": "no",
            },
            compare_args=["origin", "destination", "flight_type", "cabin", "insurance"],
            description="Book business RT JFK→SFO (one per passenger)",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "mohamed_silva_9265"}),
    ],
)


# --- TASK 24: Can't cancel H9ZU1C, book JFK→SEA basic economy ---
_SPECS["24"] = TaskSpec(
    task_id="24",
    description="User wants to remove passenger from H9ZU1C (not possible) and book "
    "cheapest direct RT from NY to West Coast. H9ZU1C does not meet cancellation policy.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="book_reservation",
            required_args={
                "flight_type": "round_trip",
                "insurance": "no",
            },
            compare_args=["flight_type", "insurance"],
            description="Book cheapest RT to West Coast, no insurance",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "mia_kim_4397"}),
    ],
)


# --- TASK 25: Book for friend, one-way DTW→SEA economy ---
_SPECS["25"] = TaskSpec(
    task_id="25",
    description="User wants to book exact same flight for friend Ivan Smith. "
    "One-way DTW→SEA economy, no baggage, no insurance. "
    "Price ≤$400 → use GC + CC (not certificate).",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="book_reservation",
            required_args={
                "origin": "DTW", "destination": "SEA",
                "flight_type": "one_way", "cabin": "economy",
                "total_baggages": 0, "insurance": "no",
            },
            compare_args=["origin", "destination", "flight_type", "cabin", "total_baggages", "insurance"],
            description="Book one-way DTW→SEA economy for Ivan Smith, no bags/insurance",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "ivan_muller_7015"}),
    ],
)


# --- TASK 26: Refuse cancellation (no valid reason) ---
_SPECS["26"] = _refuse_all(
    "26",
    "User wants to cancel MCO→CLT flights. Reservation doesn't meet cancellation policy. "
    "Agent must not cancel or offer refund.",
)


# --- TASK 27: Delayed flight complaint, no compensation (user doesn't want cancel/modify) ---
_SPECS["27"] = TaskSpec(
    task_id="27",
    description="User complains about delayed flight HAT039 ATL→SEA. "
    "Does NOT want to cancel or modify reservation. "
    "Agent should not issue certificate since user doesn't want changes.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "book_reservation", "send_certificate",
    },
    max_write_calls=0,
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "ethan_martin_2396"}),
    ],
)


# --- TASK 28: Refuse cancellation (basic economy, no insurance, can't cancel) ---
_SPECS["28"] = _refuse_all(
    "28",
    "User wants to cancel SI5UKW but it's basic economy with no insurance and >24h. "
    "Agent should not cancel or offer any refund despite user's persistence.",
)


# --- TASK 29: Cancel VA5SGQ and book new DTW→JFK RT economy ---
_SPECS["29"] = TaskSpec(
    task_id="29",
    description="User wants to change DTW→LGA to nonstop DTW→JFK. "
    "Can't change origin/destination → cancel VA5SGQ and book new. "
    "New booking: RT DTW→JFK economy, 1 bag, no insurance.",
    forbidden_write_tools={
        "update_reservation_flights", "update_reservation_passengers",
        "update_reservation_baggages", "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "VA5SGQ"},
            description="Cancel VA5SGQ (changing to DTW→JFK requires new booking)",
        ),
        ActionConstraint(
            tool_name="book_reservation",
            required_args={
                "origin": "DTW", "destination": "JFK",
                "flight_type": "round_trip", "cabin": "economy",
                "insurance": "no",
            },
            compare_args=["origin", "destination", "flight_type", "cabin", "insurance"],
            description="Book new RT DTW→JFK economy, 1 bag, no insurance",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "VA5SGQ"}),
    ],
)


# --- TASK 30: Update 1N99U6 flights (change to nonstop) ---
_SPECS["30"] = TaskSpec(
    task_id="30",
    description="User wants to change one-stop LAS→IAH to nonstop in reservation 1N99U6. "
    "Cannot remove checked bags per policy.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "1N99U6", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
            description="Update 1N99U6 to nonstop LAS→IAH flight",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "1N99U6"}),
    ],
)


# --- TASK 31: No changes (cost exceeds $100 budget) ---
_SPECS["31"] = _refuse_all(
    "31",
    "User wants to change JFK flight to nonstop but only if <$100. "
    "No suitable option exists within budget. Agent should not book or modify.",
)


# --- TASK 32: Update OWZ4XL to economy, then to nonstop ---
_SPECS["32"] = TaskSpec(
    task_id="32",
    description="User wants to upgrade OWZ4XL from basic economy to economy, "
    "then change to nonstop EWR→LAX. Budget $100. Two-step process.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "OWZ4XL", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
            description="First upgrade OWZ4XL to economy, then change to nonstop",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "ivan_rossi_8555"}),
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "OWZ4XL"}),
    ],
)


# --- TASK 33: Update HXDUBJ flights + add 2 bags ---
_SPECS["33"] = TaskSpec(
    task_id="33",
    description="User wants to change HXDUBJ outgoing to nonstop next day and push return back. "
    "Also add 2 bags. Business upgrade exceeds $200 budget so keep economy.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "HXDUBJ", "cabin": "economy"},
            compare_args=["reservation_id", "cabin"],
            description="Update HXDUBJ to new flights (economy)",
        ),
        ActionConstraint(
            tool_name="update_reservation_baggages",
            required_args={"reservation_id": "HXDUBJ", "total_baggages": 2, "nonfree_baggages": 0},
            compare_args=["reservation_id", "total_baggages", "nonfree_baggages"],
            description="Add 2 free checked bags to HXDUBJ",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "HXDUBJ"}),
    ],
)


# --- TASK 34: No changes (business + changes exceed $200 budget) ---
_SPECS["34"] = _refuse_all(
    "34",
    "User wants flight changes + business upgrade on HXDUBJ but total exceeds $200 budget. "
    "User does not accept partial changes. Agent should not make any changes.",
)


# --- TASK 35: Don't cancel, book new JFK→SFO ---
_SPECS["35"] = TaskSpec(
    task_id="35",
    description="User wants to cancel JFK→MCO (IFOYYZ) but doesn't meet policy. "
    "Also book 2nd cheapest JFK→SFO economy one-way on May 24. No bag/insurance. CC ending 7334.",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="book_reservation",
            required_args={
                "origin": "JFK", "destination": "SFO",
                "flight_type": "one_way", "cabin": "economy",
                "total_baggages": 0, "insurance": "no",
            },
            compare_args=["origin", "destination", "flight_type", "cabin", "total_baggages", "insurance"],
            description="Book one-way JFK→SFO economy, no bags/insurance",
        ),
    ],
)


# --- TASK 36: No changes (basic economy can't be modified) ---
_SPECS["36"] = TaskSpec(
    task_id="36",
    description="User wants to change date on EUJUY6 but basic economy flights cannot be modified. "
    "Agent should not change the flight. Transfer allowed if needed.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_flights", "update_reservation_baggages",
        "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(tool_name="transfer_to_human_agents"),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "EUJUY6"}),
    ],
)


# --- TASK 37: Upgrade M20IZO to business, don't cancel IFOYYZ/NQNU5R ---
_SPECS["37"] = TaskSpec(
    task_id="37",
    description="User wants to cancel IFOYYZ (doesn't meet criteria), NQNU5R (past), "
    "and upgrade M20IZO to business (CC ending 7334).",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "M20IZO", "cabin": "business"},
            compare_args=["reservation_id", "cabin"],
            description="Upgrade M20IZO to business class",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "M20IZO"}),
    ],
)


# --- TASK 38: No compensation (delayed flight, user doesn't want cancel/modify) ---
_SPECS["38"] = _refuse_all(
    "38",
    "User is frustrated about delayed flight. Does NOT want to cancel or modify. "
    "Agent should verify delay and passenger count. "
    "Should not offer certificate (user doesn't want to change/cancel).",
)
_SPECS["38"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_user_details", required_args={"user_id": "noah_muller_9847"}),
]
# Override: allow transfer
_SPECS["38"] = TaskSpec(
    task_id="38",
    description="User is frustrated about delayed flight. Does NOT want to cancel or modify. "
    "Agent should verify delay and passenger count. "
    "Should not offer certificate (user doesn't want to change/cancel).",
    forbidden_write_tools={
        "cancel_reservation", "update_reservation_flights",
        "update_reservation_baggages", "update_reservation_passengers",
        "book_reservation", "send_certificate",
    },
    allowed_write_actions=[
        ActionConstraint(tool_name="transfer_to_human_agents"),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "noah_muller_9847"}),
    ],
)


# --- TASK 39: Cancel only eligible upcoming reservations ---
_SPECS["39"] = TaskSpec(
    task_id="39",
    description="User wants to cancel ALL upcoming flights. "
    "Only 8C8K4E, LU15PA, MSJ4OA are eligible (have insurance/within 24h). "
    "Others must NOT be cancelled.",
    forbidden_write_tools={
        "book_reservation", "send_certificate",
        "update_reservation_flights", "update_reservation_baggages",
        "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "8C8K4E"},
            description="Cancel 8C8K4E",
        ),
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "LU15PA"},
            description="Cancel LU15PA",
        ),
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "MSJ4OA"},
            description="Cancel MSJ4OA",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "amelia_davis_8890"}),
    ],
)


# --- TASK 40: Update passenger on 3RK2T9 ---
_SPECS["40"] = TaskSpec(
    task_id="40",
    description="User wants to change passenger name on reservation 3RK2T9 "
    "from Mei Lee to Mei Garcia.",
    forbidden_write_tools={
        "cancel_reservation", "book_reservation", "send_certificate",
        "update_reservation_flights", "update_reservation_baggages",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_passengers",
            required_args={"reservation_id": "3RK2T9"},
            compare_args=["reservation_id"],
            description="Update passenger name to Mei Garcia on 3RK2T9",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "3RK2T9"}),
    ],
)


# --- TASK 41: Do NOT cancel any (no single-passenger upcoming flights meet criteria) ---
_SPECS["41"] = _refuse_all(
    "41",
    "User wants to cancel upcoming flights with only 1 passenger. "
    "No reservation meets BOTH single-passenger AND cancellation eligibility criteria. "
    "Agent must not cancel any reservation.",
)
_SPECS["41"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_user_details", required_args={"user_id": "amelia_davis_8890"}),
]


# --- TASK 42: Cancel duplicates FDZ0T5 and HSR97W ---
_SPECS["42"] = TaskSpec(
    task_id="42",
    description="User has duplicate bookings for same days. "
    "Cancel FDZ0T5 and HSR97W (the duplicates). Don't cancel others.",
    forbidden_write_tools={
        "book_reservation", "send_certificate",
        "update_reservation_flights", "update_reservation_baggages",
        "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "FDZ0T5"},
            description="Cancel duplicate booking FDZ0T5",
        ),
        ActionConstraint(
            tool_name="cancel_reservation",
            required_args={"reservation_id": "HSR97W"},
            description="Cancel duplicate booking HSR97W",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "sophia_martin_4574"}),
    ],
)


# --- TASK 43: Can't cancel either May 17 flight ---
_SPECS["43"] = _refuse_all(
    "43",
    "User has two flights on May 17. Wants to cancel ATL→JFK (9HBUV8) or other (D1EW9B). "
    "Neither meets cancellation policy. Agent should not cancel.",
)
_SPECS["43"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_user_details", required_args={"user_id": "mohamed_hernandez_5188"}),
]


# --- TASK 44: Upgrade NM1VX1, H8Q05L, KC18K6 to business; don't cancel S61CZX ---
_SPECS["44"] = TaskSpec(
    task_id="44",
    description="User wants to cancel reservations with flights >4h and upgrade ≤3h flights to business. "
    "S61CZX should NOT be cancelled (user is healthy). "
    "NM1VX1, H8Q05L, KC18K6 should be upgraded to business.",
    forbidden_write_tools={
        "book_reservation", "send_certificate",
        "update_reservation_baggages", "update_reservation_passengers",
    },
    allowed_write_actions=[
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "NM1VX1", "cabin": "business"},
            compare_args=["reservation_id", "cabin"],
            description="Upgrade NM1VX1 to business",
        ),
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "H8Q05L", "cabin": "business"},
            compare_args=["reservation_id", "cabin"],
            description="Upgrade H8Q05L to business",
        ),
        ActionConstraint(
            tool_name="update_reservation_flights",
            required_args={"reservation_id": "KC18K6", "cabin": "business"},
            compare_args=["reservation_id", "cabin"],
            description="Upgrade KC18K6 to business",
        ),
    ],
    required_reads_before_writes=[
        ActionConstraint(tool_name="get_user_details", required_args={"user_id": "sophia_silva_7557"}),
    ],
)


# --- TASK 45: Don't cancel or modify PEP4E0 ---
_SPECS["45"] = _refuse_all(
    "45",
    "User wants to cancel PEP4E0 for family emergency but doesn't meet policy. "
    "Also tried changing flight or adding insurance — not allowed. "
    "Agent should not cancel, change, or add insurance. No transfer.",
)
_SPECS["45"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "PEP4E0"}),
]


# --- TASK 46: Don't cancel insurance ---
_SPECS["46"] = _refuse_all(
    "46",
    "User wants to cancel insurance on H8Q05L and get refund. "
    "Insurance cannot be cancelled after booking. Agent should refuse.",
)


# --- TASK 47: Don't cancel H8Q05L ---
_SPECS["47"] = _refuse_all(
    "47",
    "User wants to cancel H8Q05L for friend's birthday. No valid cancellation reason. "
    "Agent should not cancel. No transfer.",
)
_SPECS["47"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "H8Q05L"}),
]


# --- TASK 48: Don't cancel 3RK2T9 ---
_SPECS["48"] = _refuse_all(
    "48",
    "User claims to have booked 3RK2T9 this morning (~10h ago). "
    "Reservation is actually >24h old. Agent should not cancel.",
)
_SPECS["48"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "3RK2T9"}),
]


# --- TASK 49: Don't cancel 3RK2T9 ---
_SPECS["49"] = _refuse_all(
    "49",
    "User claims insurance on 3RK2T9 to cancel. But reservation has NO insurance. "
    "Agent should not cancel.",
)
_SPECS["49"].required_reads_before_writes = [
    ActionConstraint(tool_name="get_reservation_details", required_args={"reservation_id": "3RK2T9"}),
]


def get_spec(task_id: str) -> TaskSpec:
    """Get the detailed spec for a specific airline task."""
    task_id = str(task_id)
    if task_id not in _SPECS:
        raise ValueError(f"No detailed spec for airline task {task_id}")
    return _SPECS[task_id]


def get_all_specs() -> dict[str, TaskSpec]:
    """Get all airline specs."""
    return dict(_SPECS)
