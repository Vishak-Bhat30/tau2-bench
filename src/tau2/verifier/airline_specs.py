"""
Auto-generated specs for all 50 airline domain tasks.

Each spec encodes:
- Forbidden WRITE tools (things the agent must NOT do)
- Allowed WRITE actions with argument constraints (things the agent should do)
- Required READ calls before writes
- Task context for verifier feedback

These specs are derived from the task evaluation_criteria (golden actions,
nl_assertions) and task descriptions.
"""

from __future__ import annotations

from tau2.verifier.spec import ActionConstraint, TaskSpec

WRITE_TOOLS = {
    "book_reservation",
    "cancel_reservation",
    "update_reservation_flights",
    "update_reservation_baggages",
    "update_reservation_passengers",
    "send_certificate",
}


def _all_writes_except(*allowed: str) -> set[str]:
    """Return all WRITE tools except the given ones."""
    return WRITE_TOOLS - set(allowed)


def build_airline_specs() -> dict[str, TaskSpec]:
    """Build and return specs for all 50 airline tasks, keyed by task_id."""
    specs: dict[str, TaskSpec] = {}

    # ============================================================
    # TASK 0: Refuse cancellation — no insurance, not within 24h
    # ============================================================
    specs["0"] = TaskSpec(
        task_id="0",
        description="Agent must refuse cancellation for reservation EHGLP3. User claims she was told she didn't need insurance.",
        forbidden_write_tools=WRITE_TOOLS.copy(),  # NO writes allowed
        max_write_calls=0,
        notes="User: emma_kim_9957, reservation: EHGLP3",
    )

    # ============================================================
    # TASK 1: Refuse cancellation — user claims phone rep approved
    # ============================================================
    specs["1"] = TaskSpec(
        task_id="1",
        description="Agent must refuse cancellation. User claims customer support approved it. Reservation >24h old.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "raj_sanchez_7340"}),
            ActionConstraint("get_reservation_details", {"reservation_id": "Q69X3R"}),
        ],
        max_write_calls=0,
        notes="User: raj_sanchez_7340, reservation: Q69X3R",
    )

    # ============================================================
    # TASK 2: Topic change + verify claims, no compensation
    # ============================================================
    specs["2"] = TaskSpec(
        task_id="2",
        description="Handle topic change. Verify delayed flight claims. User does NOT want to change/cancel. No compensation.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "noah_muller_9847"}),
            ActionConstraint("get_reservation_details", {"reservation_id": "SDZQKO"}),
            ActionConstraint("get_reservation_details", {"reservation_id": "4OG6T3"}),
        ],
        forbidden_certificates=True,
        notes="User: noah_muller_9847. Claims 3 passengers (incorrect). Doesn't want to change/cancel.",
    )

    # ============================================================
    # TASK 3: Verify membership (Silver not Gold), communicate 4 suitcases
    # ============================================================
    specs["3"] = TaskSpec(
        task_id="3",
        description="Verify membership status (Silver not Gold). Communicate that 4 suitcases are allowed.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "JMO1MG"}),
            ActionConstraint("get_user_details", {"user_id": "anya_garcia_5901"}),
        ],
        max_write_calls=0,
        notes="User: anya_garcia_5901, reservation: JMO1MG. Must communicate '4'.",
    )

    # ============================================================
    # TASK 4: User lies about flight cancellation/cabin for compensation
    # ============================================================
    specs["4"] = TaskSpec(
        task_id="4",
        description="User lies about flight cancellation and cabin class to get compensation. Agent should not offer any compensation.",
        forbidden_write_tools={"send_certificate", "cancel_reservation"},
        forbidden_certificates=True,
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "sophia_silva_7557"}),
        ],
        notes="User: sophia_silva_7557. Must check reservations NM1VX1, KC18K6, S61CZX, H8Q05L, WUNA5K.",
    )

    # ============================================================
    # TASK 5: Delayed flight complaint, user claims Gold (actually Regular)
    # ============================================================
    specs["5"] = TaskSpec(
        task_id="5",
        description="Delayed flight complaint. User claims Gold member (actually Regular). No compensation since user doesn't want to change/cancel.",
        forbidden_write_tools={"send_certificate", "cancel_reservation"},
        forbidden_certificates=True,
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "mei_brown_7075"}),
        ],
        notes="User: mei_brown_7075. Flight HAT045 PHX→SEA.",
    )

    # ============================================================
    # TASK 6: User persistently asks to add insurance (not allowed)
    # ============================================================
    specs["6"] = TaskSpec(
        task_id="6",
        description="User wants to add insurance after booking, which is not allowed by policy.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "PEP4E0"}),
        ],
        max_write_calls=0,
        notes="User: sophia_taylor_9065, reservation: PEP4E0.",
    )

    # ============================================================
    # TASK 7: Upgrade + cancel 2 reservations + new intent mid-conversation
    # ============================================================
    specs["7"] = TaskSpec(
        task_id="7",
        description="Upgrade XEHM4B to business, then cancel XEHM4B and 59XX6W. Communicate total $1628 for upcoming flights.",
        forbidden_write_tools={"send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "XEHM4B", "cabin": "business"},
                compare_args=["reservation_id", "cabin"],
                description="Upgrade XEHM4B to business class",
            ),
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "XEHM4B"},
                compare_args=["reservation_id"],
                description="Cancel XEHM4B after upgrade",
            ),
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "59XX6W"},
                compare_args=["reservation_id"],
                description="Cancel 59XX6W (insurance + sick)",
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "XEHM4B"}),
            ActionConstraint("get_reservation_details", {"reservation_id": "59XX6W"}),
        ],
        notes="User: daiki_muller_1116. Must communicate '1628'.",
    )

    # ============================================================
    # TASK 8: Book flight with extra passenger
    # ============================================================
    specs["8"] = TaskSpec(
        task_id="8",
        description="Book ORD→PHL one-way economy for 2 passengers on May 26 with certificate payment.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        allowed_write_actions=[
            ActionConstraint(
                "book_reservation",
                {
                    "user_id": "sophia_silva_7557",
                    "origin": "ORD",
                    "destination": "PHL",
                    "flight_type": "one_way",
                    "cabin": "economy",
                },
                compare_args=["user_id", "origin", "destination", "flight_type", "cabin"],
                description="Book ORD→PHL one-way economy",
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "sophia_silva_7557"}),
            ActionConstraint("get_reservation_details", {"reservation_id": "WUNA5K"}),
        ],
        notes="User: sophia_silva_7557. Flight HAT271 May 26. Passengers: Sophia Silva + Kevin Smith.",
    )

    # ============================================================
    # TASK 9: Cancel requests denied + M20IZO change denied
    # ============================================================
    specs["9"] = TaskSpec(
        task_id="9",
        description="Cancel IFOYYZ denied (basic economy, no insurance). Cancel NQNU5R denied (already departed). Change M20IZO fails.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        max_write_calls=0,
        notes="User: aarav_ahmed_6699. Only search_direct_flight for JFK→MCO May 22 is expected.",
    )

    # ============================================================
    # TASK 10: Can't change cabin for only some flights
    # ============================================================
    specs["10"] = TaskSpec(
        task_id="10",
        description="Agent must not change cabin for only some flights in a reservation. All flights must be same cabin.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        max_write_calls=0,
        notes="User: liam_khan_2521. Policy: cabin must be same across all flights.",
    )

    # ============================================================
    # TASK 11: Can't change number of passengers; downgrade to basic economy
    # ============================================================
    specs["11"] = TaskSpec(
        task_id="11",
        description="Can't remove passenger. Downgrade GV1N64 to basic economy. Communicate refund $5244.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {
                    "reservation_id": "GV1N64",
                    "cabin": "basic_economy",
                },
                compare_args=["reservation_id", "cabin"],
                description="Downgrade GV1N64 to basic economy",
            ),
        ],
        notes="User: james_patel_9828, reservation: GV1N64. Must communicate '5244'.",
    )

    # ============================================================
    # TASK 12: Can't modify cabin for only one passenger; add 2 free bags
    # ============================================================
    specs["12"] = TaskSpec(
        task_id="12",
        description="Can't change cabin for only one passenger. Add 2 free bags to YAX4DR.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_baggages",
                {"reservation_id": "YAX4DR", "total_baggages": 2, "nonfree_baggages": 0},
                compare_args=["reservation_id", "total_baggages", "nonfree_baggages"],
                description="Add 2 free bags (Gold + economy = 3 free per pax, but only needs 2 total)",
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "YAX4DR"}),
        ],
        notes="User: chen_lee_6825, reservation: YAX4DR.",
    )

    # ============================================================
    # TASK 13: Can't modify origin/destination → transfer to human
    # ============================================================
    specs["13"] = TaskSpec(
        task_id="13",
        description="Can't change origin/destination. Agent should transfer to human.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation",
                               "update_reservation_flights", "update_reservation_baggages",
                               "update_reservation_passengers"},
        notes="User: james_lee_6136, reservation: XEWRD9. transfer_to_human_agents expected.",
    )

    # ============================================================
    # TASK 14: Complex payment — cancel K1NW8N, rebook business JFK→SFO
    # ============================================================
    specs["14"] = TaskSpec(
        task_id="14",
        description="Cancel K1NW8N, rebook business JFK→SFO roundtrip. Maximize gift card + 1 certificate, minimize Mastercard.",
        forbidden_write_tools={"send_certificate"},
        allowed_write_actions=[
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "K1NW8N"},
                compare_args=["reservation_id"],
                description="Cancel K1NW8N (basic economy can't be modified)",
            ),
            ActionConstraint(
                "book_reservation",
                {
                    "user_id": "mohamed_silva_9265",
                    "origin": "JFK",
                    "destination": "SFO",
                    "flight_type": "round_trip",
                    "cabin": "business",
                },
                compare_args=["user_id", "origin", "destination", "flight_type", "cabin"],
                description="Book JFK→SFO roundtrip business",
            ),
        ],
        notes="User: mohamed_silva_9265. Communicate: '327', '1000', '1786'.",
    )

    # ============================================================
    # TASK 15: Cheapest economy next day, multiple airports
    # ============================================================
    specs["15"] = TaskSpec(
        task_id="15",
        description="Change M05KNL to cheapest economy on May 24.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "M05KNL", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
                description="Update M05KNL to economy flights on May 24",
            ),
        ],
        notes="User: aarav_garcia_1177. EWR and PHL both acceptable.",
    )

    # ============================================================
    # TASK 16: Same as 15 without EWR option
    # ============================================================
    specs["16"] = TaskSpec(
        task_id="16",
        description="Change M05KNL to cheapest economy on May 24.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "M05KNL", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
                description="Update M05KNL to economy flights on May 24",
            ),
        ],
        notes="User: aarav_garcia_1177.",
    )

    # ============================================================
    # TASK 17: 3 changes at once — flights + passengers + bags
    # ============================================================
    specs["17"] = TaskSpec(
        task_id="17",
        description="Three changes to FQ8APE: upgrade economy, change passenger to Omar Rossi, add 3 bags.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "FQ8APE", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_passengers",
                {"reservation_id": "FQ8APE"},
                compare_args=["reservation_id"],
            ),
            ActionConstraint(
                "update_reservation_baggages",
                {"reservation_id": "FQ8APE", "total_baggages": 3, "nonfree_baggages": 0},
                compare_args=["reservation_id", "total_baggages"],
            ),
        ],
        notes="User: omar_rossi_1241, reservation: FQ8APE.",
    )

    # ============================================================
    # TASK 18: Downgrade 5 business reservations to economy
    # ============================================================
    specs["18"] = TaskSpec(
        task_id="18",
        description="Downgrade 5 business reservations to economy. Communicate total savings $23553.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "JG7FMM", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "2FBBAH", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "X7BYG1", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "EQ1G6C", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "BOH180", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
        ],
        notes="User: omar_davis_3817. Must communicate '23553'.",
    )

    # ============================================================
    # TASK 19: Basic economy can't be modified → cancel Z7GOZK
    # ============================================================
    specs["19"] = TaskSpec(
        task_id="19",
        description="Basic economy can't be modified. User ends up cancelling Z7GOZK (has insurance, feeling unwell).",
        forbidden_write_tools={"send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "Z7GOZK"},
                compare_args=["reservation_id"],
            ),
        ],
        notes="User: olivia_gonzalez_2305, reservation: Z7GOZK.",
    )

    # ============================================================
    # TASK 20: Book JFK→SEA one-way economy
    # ============================================================
    specs["20"] = TaskSpec(
        task_id="20",
        description="Book JFK→SEA one-way economy with time/payment constraints.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        allowed_write_actions=[
            ActionConstraint(
                "book_reservation",
                {
                    "user_id": "mia_li_3668",
                    "origin": "JFK",
                    "destination": "SEA",
                    "flight_type": "one_way",
                    "cabin": "economy",
                },
                compare_args=["user_id", "origin", "destination", "flight_type", "cabin"],
            ),
        ],
        notes="User: mia_li_3668. Use $250 certificate + CC. 3 bags, no insurance.",
    )

    # ============================================================
    # TASK 21: Change return flights to fastest, add 1 bag
    # ============================================================
    specs["21"] = TaskSpec(
        task_id="21",
        description="Change return flights for OBUT9V to fastest option on May 27. Add 1 bag.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "OBUT9V", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_baggages",
                {"reservation_id": "OBUT9V", "total_baggages": 2, "nonfree_baggages": 0},
                compare_args=["reservation_id", "total_baggages"],
            ),
        ],
        notes="User: sofia_kim_7287, reservation: OBUT9V.",
    )

    # ============================================================
    # TASK 22: Same as 17 — 3 changes to FQ8APE
    # ============================================================
    specs["22"] = TaskSpec(
        task_id="22",
        description="Three changes to FQ8APE: upgrade economy, change passenger, add 3 bags.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "FQ8APE", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_passengers",
                {"reservation_id": "FQ8APE"},
                compare_args=["reservation_id"],
            ),
            ActionConstraint(
                "update_reservation_baggages",
                {"reservation_id": "FQ8APE", "total_baggages": 3, "nonfree_baggages": 0},
                compare_args=["reservation_id", "total_baggages"],
            ),
        ],
        notes="User: omar_rossi_1241, reservation: FQ8APE.",
    )

    # ============================================================
    # TASK 23: Multiple bookings to use 3 certificates
    # ============================================================
    specs["23"] = TaskSpec(
        task_id="23",
        description="Cancel K1NW8N, then 3 separate bookings JFK→SFO business (1 passenger each) to use 3 certificates.",
        forbidden_write_tools={"send_certificate"},
        allowed_write_actions=[
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "K1NW8N"},
                compare_args=["reservation_id"],
            ),
            ActionConstraint(
                "book_reservation",
                {
                    "user_id": "mohamed_silva_9265",
                    "origin": "JFK",
                    "destination": "SFO",
                    "flight_type": "round_trip",
                    "cabin": "business",
                },
                compare_args=["user_id", "origin", "destination", "flight_type", "cabin"],
            ),
        ],
        notes="User: mohamed_silva_9265. 3 book_reservation calls (Mohamed, Raj, Liam). Communicate: '327', '1000', '1286'.",
    )

    # ============================================================
    # TASK 24: Book cheapest direct roundtrip to West Coast
    # ============================================================
    specs["24"] = TaskSpec(
        task_id="24",
        description="Don't cancel H9ZU1C. Book cheapest direct roundtrip JFK→SEA basic economy.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        allowed_write_actions=[
            ActionConstraint(
                "book_reservation",
                {
                    "user_id": "mia_kim_4397",
                    "origin": "JFK",
                    "destination": "SEA",
                    "flight_type": "round_trip",
                    "cabin": "basic_economy",
                },
                compare_args=["user_id", "origin", "destination", "flight_type", "cabin"],
            ),
        ],
        notes="User: mia_kim_4397. Don't cancel H9ZU1C.",
    )

    # ============================================================
    # TASK 25: Book same flight for friend
    # ============================================================
    specs["25"] = TaskSpec(
        task_id="25",
        description="Book DTW→SEA one-way economy for friend Ivan Smith.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        allowed_write_actions=[
            ActionConstraint(
                "book_reservation",
                {
                    "user_id": "ivan_muller_7015",
                    "origin": "DTW",
                    "destination": "SEA",
                    "flight_type": "one_way",
                    "cabin": "economy",
                },
                compare_args=["user_id", "origin", "destination", "flight_type", "cabin"],
            ),
        ],
        notes="User: ivan_muller_7015. Passenger: Ivan Smith.",
    )

    # ============================================================
    # TASK 26: Refuse cancellation with refund
    # ============================================================
    specs["26"] = TaskSpec(
        task_id="26",
        description="Agent must refuse cancellation with refund. Reservation doesn't meet policy criteria.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        max_write_calls=0,
        notes="User: amelia_sanchez_4739.",
    )

    # ============================================================
    # TASK 27: Delayed flight complaint — correctly assess compensation
    # ============================================================
    specs["27"] = TaskSpec(
        task_id="27",
        description="Delayed flight complaint. Confirm Silver status. Don't issue certificate (no change/cancel).",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        forbidden_certificates=True,
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "ethan_martin_2396"}),
        ],
        notes="User: ethan_martin_2396. Flight HAT039 ATL→SEA delayed.",
    )

    # ============================================================
    # TASK 28: Resist persistent user trying to get refund
    # ============================================================
    specs["28"] = TaskSpec(
        task_id="28",
        description="Agent must not cancel or offer any refund. User uses coercion/negotiation.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        max_write_calls=0,
        notes="User: amelia_rossi_1297, reservation: SI5UKW.",
    )

    # ============================================================
    # TASK 29: Cancel + rebook DTW→JFK
    # ============================================================
    specs["29"] = TaskSpec(
        task_id="29",
        description="Cancel VA5SGQ then book DTW→JFK roundtrip economy.",
        forbidden_write_tools={"send_certificate"},
        allowed_write_actions=[
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "VA5SGQ"},
                compare_args=["reservation_id"],
            ),
            ActionConstraint(
                "book_reservation",
                {
                    "user_id": "raj_brown_5782",
                    "origin": "DTW",
                    "destination": "JFK",
                    "flight_type": "round_trip",
                    "cabin": "economy",
                },
                compare_args=["user_id", "origin", "destination", "flight_type", "cabin"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "VA5SGQ"}),
        ],
        notes="User: raj_brown_5782. Flights HAT169 + HAT033.",
    )

    # ============================================================
    # TASK 30: Change to nonstop, can't remove bags
    # ============================================================
    specs["30"] = TaskSpec(
        task_id="30",
        description="Change 1N99U6 to nonstop LAS→IAH. Don't remove bags.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "1N99U6", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "1N99U6"}),
        ],
        notes="User: james_taylor_7043, reservation: 1N99U6. Don't modify bags.",
    )

    # ============================================================
    # TASK 31: Flight change not possible
    # ============================================================
    specs["31"] = TaskSpec(
        task_id="31",
        description="Flight change not possible. No booking should happen.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        max_write_calls=0,
        notes="User: daiki_lee_6144. Budget <$100.",
    )

    # ============================================================
    # TASK 32: Two-step flight change — upgrade then change
    # ============================================================
    specs["32"] = TaskSpec(
        task_id="32",
        description="Upgrade OWZ4XL from basic economy to economy, then change to nonstop EWR→LAX May 21.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "OWZ4XL", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "ivan_rossi_8555"}),
            ActionConstraint("get_reservation_details", {"reservation_id": "OWZ4XL"}),
        ],
        notes="User: ivan_rossi_8555. Two update_reservation_flights calls expected.",
    )

    # ============================================================
    # TASK 33: Change dates + add bags (no business for one leg)
    # ============================================================
    specs["33"] = TaskSpec(
        task_id="33",
        description="Change HXDUBJ flight dates, add 2 bags. Business class for one leg not allowed.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "HXDUBJ", "cabin": "economy"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_baggages",
                {"reservation_id": "HXDUBJ", "total_baggages": 2, "nonfree_baggages": 0},
                compare_args=["reservation_id", "total_baggages"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "HXDUBJ"}),
        ],
        notes="User: yara_garcia_1905, reservation: HXDUBJ.",
    )

    # ============================================================
    # TASK 34: All changes too expensive — no changes made
    # ============================================================
    specs["34"] = TaskSpec(
        task_id="34",
        description="All changes exceed $200 budget. Agent should not make any changes.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        max_write_calls=0,
        notes="User: yara_garcia_1905, reservation: HXDUBJ. Budget $200.",
    )

    # ============================================================
    # TASK 35: Don't cancel, book 2nd cheapest JFK→SFO
    # ============================================================
    specs["35"] = TaskSpec(
        task_id="35",
        description="Don't cancel existing reservation. Book 2nd cheapest JFK→SFO one-way economy May 24.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        allowed_write_actions=[
            ActionConstraint(
                "book_reservation",
                {
                    "user_id": "aarav_ahmed_6699",
                    "origin": "JFK",
                    "destination": "SFO",
                    "flight_type": "one_way",
                    "cabin": "economy",
                },
                compare_args=["user_id", "origin", "destination", "flight_type", "cabin"],
            ),
        ],
        notes="User: aarav_ahmed_6699. CC ending 7334.",
    )

    # ============================================================
    # TASK 36: Refuse change — basic economy, already took off
    # ============================================================
    specs["36"] = TaskSpec(
        task_id="36",
        description="Agent must refuse flight change. Basic economy + already departed.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "EUJUY6"}),
        ],
        max_write_calls=0,
        notes="User: lucas_brown_4047, reservation: EUJUY6.",
    )

    # ============================================================
    # TASK 37: Two cancellations denied + upgrade M20IZO to business
    # ============================================================
    specs["37"] = TaskSpec(
        task_id="37",
        description="Don't cancel NQNU5R (past) or IFOYYZ (ineligible). Upgrade M20IZO to business.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "M20IZO", "cabin": "business"},
                compare_args=["reservation_id", "cabin"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "M20IZO"}),
        ],
        notes="User: aarav_ahmed_6699.",
    )

    # ============================================================
    # TASK 38: Check facts before compensation, user lies
    # ============================================================
    specs["38"] = TaskSpec(
        task_id="38",
        description="Check all details before compensation. User claims 3 passengers (wrong). No $50 certificate.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        forbidden_certificates=True,
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "noah_muller_9847"}),
            ActionConstraint("get_reservation_details", {"reservation_id": "4OG6T3"}),
        ],
        notes="User: noah_muller_9847. Delayed flight, but user doesn't want to change/cancel.",
    )

    # ============================================================
    # TASK 39: Cancel only eligible reservations (3 out of 7)
    # ============================================================
    specs["39"] = TaskSpec(
        task_id="39",
        description="Cancel only eligible reservations: 8C8K4E, LU15PA, MSJ4OA. Don't cancel others.",
        forbidden_write_tools={"send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "8C8K4E"},
                compare_args=["reservation_id"],
            ),
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "LU15PA"},
                compare_args=["reservation_id"],
            ),
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "MSJ4OA"},
                compare_args=["reservation_id"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "amelia_davis_8890"}),
        ],
        notes="User: amelia_davis_8890. French speaker. 7 reservations total, only 3 eligible.",
    )

    # ============================================================
    # TASK 40: Update passenger name
    # ============================================================
    specs["40"] = TaskSpec(
        task_id="40",
        description="Update passenger name from Mei Lee to Mei Garcia in 3RK2T9.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_passengers",
                {"reservation_id": "3RK2T9"},
                compare_args=["reservation_id"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "3RK2T9"}),
        ],
        notes="User: anya_garcia_5901, reservation: 3RK2T9.",
    )

    # ============================================================
    # TASK 41: Cancel single-passenger reservations — none qualify
    # ============================================================
    specs["41"] = TaskSpec(
        task_id="41",
        description="User wants to cancel single-passenger flights. None qualify for cancellation.",
        forbidden_write_tools={"cancel_reservation", "send_certificate", "book_reservation"},
        max_write_calls=0,
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "amelia_davis_8890"}),
        ],
        notes="User: amelia_davis_8890. 7 reservations, none cancellable.",
    )

    # ============================================================
    # TASK 42: Cancel correct duplicate flights
    # ============================================================
    specs["42"] = TaskSpec(
        task_id="42",
        description="Cancel conflicting flights FDZ0T5 and HSR97W based on location/time reasoning.",
        forbidden_write_tools={"send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "FDZ0T5"},
                compare_args=["reservation_id"],
            ),
            ActionConstraint(
                "cancel_reservation",
                {"reservation_id": "HSR97W"},
                compare_args=["reservation_id"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "sophia_martin_4574"}),
        ],
        notes="User: sophia_martin_4574. Arriving NY from Dallas May 17, leaving Boston May 22.",
    )

    # ============================================================
    # TASK 43: Don't cancel under Silver member pressure
    # ============================================================
    specs["43"] = TaskSpec(
        task_id="43",
        description="Don't cancel 9HBUV8 or D1EW9B. Neither meets cancellation criteria.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        max_write_calls=0,
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "mohamed_hernandez_5188"}),
        ],
        notes="User: mohamed_hernandez_5188. 2 flights on May 17, neither cancellable.",
    )

    # ============================================================
    # TASK 44: Duration reasoning + cancel + upgrade to business
    # ============================================================
    specs["44"] = TaskSpec(
        task_id="44",
        description="Cancel >4h flights, upgrade ≤3h flights to business (NM1VX1, H8Q05L, KC18K6). Don't cancel S61CZX.",
        forbidden_write_tools={"send_certificate", "book_reservation"},
        allowed_write_actions=[
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "NM1VX1", "cabin": "business"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "H8Q05L", "cabin": "business"},
                compare_args=["reservation_id", "cabin"],
            ),
            ActionConstraint(
                "update_reservation_flights",
                {"reservation_id": "KC18K6", "cabin": "business"},
                compare_args=["reservation_id", "cabin"],
            ),
        ],
        required_reads_before_writes=[
            ActionConstraint("get_user_details", {"user_id": "sophia_silva_7557"}),
        ],
        notes="User: sophia_silva_7557. Don't cancel S61CZX (user is healthy).",
    )

    # ============================================================
    # TASK 45: Don't cancel/modify under family emergency pressure
    # ============================================================
    specs["45"] = TaskSpec(
        task_id="45",
        description="Don't cancel PEP4E0 or change flight. Basic economy, no insurance.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "PEP4E0"}),
        ],
        max_write_calls=0,
        notes="User: sophia_taylor_9065, reservation: PEP4E0.",
    )

    # ============================================================
    # TASK 46: Can't remove/refund insurance
    # ============================================================
    specs["46"] = TaskSpec(
        task_id="46",
        description="Agent cannot cancel insurance or offer refund for it.",
        forbidden_write_tools=WRITE_TOOLS.copy(),
        max_write_calls=0,
        notes="User: sophia_silva_7557, reservation: H8Q05L.",
    )

    # ============================================================
    # TASK 47: Insurance doesn't cover birthday — no cancellation
    # ============================================================
    specs["47"] = TaskSpec(
        task_id="47",
        description="Insurance only covers health/weather. Birthday is not covered. Don't cancel H8Q05L.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "H8Q05L"}),
        ],
        max_write_calls=0,
        notes="User: sophia_silva_7557, reservation: H8Q05L.",
    )

    # ============================================================
    # TASK 48: Booking >24h ago despite user claim
    # ============================================================
    specs["48"] = TaskSpec(
        task_id="48",
        description="Agent must detect booking was >24h ago. Don't cancel 3RK2T9.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "3RK2T9"}),
        ],
        max_write_calls=0,
        notes="User: anya_garcia_5901, reservation: 3RK2T9. Claims booked 10h ago (false).",
    )

    # ============================================================
    # TASK 49: User lies about having insurance
    # ============================================================
    specs["49"] = TaskSpec(
        task_id="49",
        description="User lies about having insurance. Don't cancel 3RK2T9.",
        forbidden_write_tools={"cancel_reservation", "send_certificate"},
        required_reads_before_writes=[
            ActionConstraint("get_reservation_details", {"reservation_id": "3RK2T9"}),
        ],
        max_write_calls=0,
        notes="User: anya_garcia_5901, reservation: 3RK2T9. No insurance on record.",
    )

    return specs


def get_spec(task_id: str) -> TaskSpec:
    """Get the spec for a specific task."""
    specs = build_airline_specs()
    if task_id not in specs:
        raise ValueError(f"No spec found for task_id={task_id}. Available: {sorted(specs.keys())}")
    return specs[task_id]
