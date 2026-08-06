"""
PolicyVerifier — intercepts tool calls in the orchestrator and checks them
against the domain policy spec before execution.

It verifies each write-tool call against policy rules and returns feedback when
a call violates policy, so the orchestrator can block it. Retail can optionally
add separate trace-derived checks with ``TAU2_RETAIL_TRACE_VERIFIERS=1``.

Usage:
    verifier = PolicyVerifier(db=flight_db, domain="airline")
    result = verifier.verify(tool_name, tool_args, conversation)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Write tools per domain
WRITE_TOOLS_BY_DOMAIN = {
    "airline": {
        "book_reservation",
        "update_reservation_flights",
        "update_reservation_baggages",
        "update_reservation_passengers",
        "cancel_reservation",
        "send_certificate",
        "transfer_to_human_agents",
    },
    "retail": {
        "cancel_pending_order",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "modify_pending_order_address",
        "return_delivered_order_items",
        "exchange_delivered_order_items",
        "modify_user_address",
        "transfer_to_human_agents",
    },
    "telecom": {
        "suspend_line",
        "resume_line",
        "send_payment_request",
        "refuel_data",
        "enable_roaming",
        "disable_roaming",
        "transfer_to_human_agents",
    },
}

# User-side write tools (executed by user, not agent — tracked for completion)
USER_WRITE_TOOLS_TELECOM = {
    "toggle_airplane_mode",
    "toggle_data",
    "set_network_mode_preference",
    "toggle_data_saver_mode",
    "disconnect_vpn",
    "connect_vpn",
    "reseat_sim_card",
    "grant_app_permission",
    "toggle_roaming",
    "set_apn_settings",
    "reset_apn_settings",
    "toggle_wifi",
    "toggle_wifi_calling",
    "reboot_device",
    "make_payment",
}

# Read-only tools per domain (skip policy checks)
READ_TOOLS_BY_DOMAIN = {
    "airline": {
        "get_user_details", "get_reservation_details",
        "search_direct_flight", "search_onestop_flight",
        "list_all_airports", "calculate", "get_flight_status",
    },
    "retail": {
        "find_user_id_by_email", "find_user_id_by_name_zip",
        "get_order_details", "get_product_details",
        "get_item_details", "get_user_details",
        "list_all_product_types", "calculate",
    },
    "telecom": {
        "get_customer_by_phone", "get_customer_by_id",
        "get_customer_by_name", "get_details_by_id",
        "get_bills_for_customer", "get_data_usage",
        "calculate", "think",
    },
}


class PolicyVerifier:
    """
    Verifies tool calls against domain policy rules.

    Parameters
    ----------
    db : The domain database (e.g. FlightDB for airline).
    domain : str
        Which domain's policy to use ("airline" for now).
    cheap_only : bool
        If True, only run DB-checkable rules (no SLM calls).
    max_feedback_per_tool : int
        After this many blocks on the same tool, allow through (safety valve).
    max_nudges : int
        Maximum number of completion nudges before giving up.
    """

    def __init__(
        self,
        db,
        domain: str = "airline",
        cheap_only: bool = False,
        max_feedback_per_tool: int = 3,
        max_nudges: int = 2,
    ):
        self.db = db
        # telecom-workflow shares the telecom tool-call policy/spec, so treat it
        # as "telecom" for verification purposes.
        if domain == "telecom-workflow":
            domain = "telecom"
        self.domain = domain
        self.cheap_only = cheap_only
        self.max_feedback_per_tool = max_feedback_per_tool
        self.max_nudges = max_nudges

        # Whether the SLM-based *argument/action* rules are allowed to BLOCK a
        # write (action-type match, item-variant match, ID accuracy). With a
        # small/unreliable SLM these produce false positives that block
        # otherwise-correct writes, so they are OFF by default and only the
        # deterministic, high-precision rules block. Set TAU2_VERIFIER_SLM_BLOCK=1
        # to re-enable them (e.g. when using a stronger SLM).
        self._slm_block = os.getenv("TAU2_VERIFIER_SLM_BLOCK", "0") == "1"

        # Maximum in-character reminders to send the user simulator per task
        # (verifier #3 — user impersonation correction).
        self.max_user_reminders = 2
        self._user_reminder_count = 0
        self._completion_nudge_count = 0

        # Track how many times we've blocked each (tool, args) pair (safety valve)
        # Key = (tool_name, frozenset of arg items) so same call+args bypasses after N blocks
        self._block_counts: dict[tuple, int] = {}

        # Track which write tools have been successfully called
        self._called_write_tools: list[str] = []

        # Track ALL tool calls (including reads) for pre-condition checks
        self._called_all_tools: list[str] = []

        # Track completed actions with details (tool_name + summary of args)
        self._completed_actions: list[str] = []

        # Retained (always empty) for backward-compat: some telecom rules read
        # this via getattr and simply no-op when it is empty. The oracle-based
        # task classification / completion nudge that used to populate it have
        # been removed so the verifier never reads the hidden user scenario.
        self._user_instructions: str = ""

        # Track user-side tool calls (for telecom completion tracking)
        self._called_user_tools: list[str] = []

        # Expected user-side tools (for telecom)
        self._expected_user_tools: list[str] = []

        # User's phone number (captured from get_customer_by_phone calls)
        self._user_phone: str | None = None

        # Track last result for specific diagnostic tools (for post-exec feedback)
        self._last_tool_results: dict[str, str] = {}

        # Domain-specific tool sets
        self._write_tools = WRITE_TOOLS_BY_DOMAIN.get(domain, set())
        self._read_tools = READ_TOOLS_BY_DOMAIN.get(domain, set())

        # Load the appropriate spec module
        self._check_read = None  # read-tool checker (if available)
        if domain == "airline":
            from tau2.verifier.airline_policy_spec import check_all, check_read
            self._check_all = check_all
            self._check_read = check_read
        elif domain == "retail":
            from tau2.verifier.retail_policy_spec import check_all
            self._check_all = check_all
        elif domain == "telecom":
            if os.environ.get("TAU2_USE_AUTO_GLUE"):
                from tau2.verifier.telecom_glue_spec import check_all
                logger.info(
                    "PolicyVerifier: using auto-generated telecom policy spec "
                    "(TAU2_USE_AUTO_GLUE set)"
                )
            else:
                from tau2.verifier.telecom_policy_spec import check_all
            self._check_all = check_all
        else:
            raise ValueError(f"No policy spec for domain: {domain}")

    @staticmethod
    def _make_args_key(tool_name: str, tool_args: dict) -> tuple:
        """Create a hashable key from (tool_name, args) for the safety-valve counter."""
        try:
            frozen = frozenset(sorted((k, str(v)) for k, v in tool_args.items()))
        except Exception:
            frozen = frozenset()
        return (tool_name, frozen)

    def record_tool_call(self, tool_name: str, tool_args: dict | None = None) -> None:
        """Record that a tool was successfully called (not blocked)."""
        self._called_all_tools.append(tool_name)
        # Capture user phone from get_customer_by_phone for result checks
        if tool_name == "get_customer_by_phone" and tool_args:
            phone = tool_args.get("phone_number", "")
            if phone:
                self._user_phone = phone
                logger.info("Captured user phone: %s", phone)
        if tool_name in self._write_tools:
            self._called_write_tools.append(tool_name)
            # Build a compact summary of what was done
            summary = self._summarize_action(tool_name, tool_args or {})
            self._completed_actions.append(summary)
            logger.info("Recorded action: %s", summary)
            if (
                self.domain == "retail"
                and os.getenv("TAU2_RETAIL_TRACE_VERIFIERS", "0") == "1"
            ):
                from tau2.verifier.retail_trace_verifiers import record_successful_write

                record_successful_write(self, tool_name, tool_args or {})

    def configure_simulation(self, simulation_id: str, task_id: str) -> None:
        """Configure per-simulation trace state when the opt-in mode is active."""
        if (
            self.domain == "retail"
            and os.getenv("TAU2_RETAIL_TRACE_VERIFIERS", "0") == "1"
        ):
            from tau2.verifier.retail_trace_verifiers import configure_state

            configure_state(self, simulation_id, task_id)

    def update_conversation_state(
        self, conversation: list[dict], user_text: str
    ) -> None:
        if (
            self.domain == "retail"
            and os.getenv("TAU2_RETAIL_TRACE_VERIFIERS", "0") == "1"
        ):
            from tau2.verifier.retail_trace_verifiers import update_from_user_turn

            update_from_user_turn(self, conversation, user_text)

    def completion_feedback(self) -> str | None:
        """Return a bounded completion nudge for unresolved trace-state requests."""
        if (
            self.domain != "retail"
            or os.getenv("TAU2_RETAIL_TRACE_VERIFIERS", "0") != "1"
            or self._completion_nudge_count >= self.max_nudges
        ):
            return None
        from tau2.verifier.retail_trace_verifiers import completion_feedback

        feedback = completion_feedback(self)
        if feedback:
            self._completion_nudge_count += 1
        return feedback

    def user_completion_feedback(self) -> str | None:
        """Keep the simulated customer engaged while current work is unresolved."""
        feedback = self.completion_feedback()
        if not feedback:
            return None
        return (
            "Stay in character as the customer and do not emit ###STOP### yet. "
            "Briefly remind the agent of the latest unresolved decision. " + feedback
        )

    def conversation_complete(self, user_text: str) -> bool:
        if (
            self.domain != "retail"
            or os.getenv("TAU2_RETAIL_TRACE_VERIFIERS", "0") != "1"
        ):
            return False
        from tau2.verifier.retail_trace_verifiers import conversation_complete

        return conversation_complete(self, user_text)

    @staticmethod
    def _summarize_action(tool_name: str, tool_args: dict) -> str:
        """Create a human-readable summary of a completed tool call."""
        if tool_name == "book_reservation":
            return (
                f"Booked {tool_args.get('flight_type', '?')} {tool_args.get('cabin', '?')} "
                f"flight {tool_args.get('origin', '?')}->{tool_args.get('destination', '?')} "
                f"for {len(tool_args.get('passengers', []))} passenger(s)"
            )
        elif tool_name == "cancel_reservation":
            return f"Cancelled reservation {tool_args.get('reservation_id', '?')}"
        elif tool_name == "update_reservation_flights":
            flights = tool_args.get('flights', [])
            fns = [f.get('flight_number', '?') if isinstance(f, dict) else '?' for f in flights]
            return (
                f"Updated flights on reservation {tool_args.get('reservation_id', '?')} "
                f"to cabin={tool_args.get('cabin', '?')}, flights={','.join(fns)}"
            )
        elif tool_name == "update_reservation_baggages":
            return (
                f"Updated baggage on reservation {tool_args.get('reservation_id', '?')} "
                f"to {tool_args.get('total_baggages', '?')} total bags"
            )
        elif tool_name == "update_reservation_passengers":
            pax = tool_args.get('passengers', [])
            names = [f"{p.get('first_name', '?')} {p.get('last_name', '?')}" if isinstance(p, dict) else '?' for p in pax]
            return (
                f"Updated passengers on reservation {tool_args.get('reservation_id', '?')} "
                f"to [{', '.join(names)}]"
            )
        elif tool_name == "send_certificate":
            return (
                f"Sent ${tool_args.get('amount', '?')} certificate to {tool_args.get('user_id', '?')}"
            )
        elif tool_name == "transfer_to_human_agents":
            return f"Transferred to human agent: {tool_args.get('summary', '?')[:100]}"
        else:
            return f"{tool_name}({', '.join(f'{k}={v}' for k, v in list(tool_args.items())[:3])})"

    def record_user_tool_call(self, tool_name: str) -> None:
        """Record a user-side tool call (for telecom completion tracking)."""
        if tool_name in USER_WRITE_TOOLS_TELECOM:
            self._called_user_tools.append(tool_name)
            logger.info("Recorded user tool call: %s (total: %d)", tool_name, len(self._called_user_tools))

    def check_result(
        self,
        tool_name: str,
        tool_args: dict,
        result_content: str,
    ) -> str | None:
        """Check a tool result after execution for post-hoc warnings.

        Returns a warning string to append to the result, or None.
        """
        if self.domain == "telecom":
            from tau2.verifier.telecom_policy_spec import (
                check_result_line_phone,
                check_result_speed_test,
                check_result_can_send_mms,
                check_result_get_data_usage,
                check_result_check_network_status,
                check_result_line_suspended,
            )
            # Track results from diagnostic tools for cross-referencing
            _TRACKED_TOOLS = {
                "check_app_permissions", "check_network_status",
                "check_wifi_calling_status", "check_apn_settings",
                "check_data_restriction_status", "check_vpn_status",
                "check_network_mode_preference", "get_data_usage",
            }
            if tool_name in _TRACKED_TOOLS:
                self._last_tool_results[tool_name] = result_content

            warnings = []
            w1 = check_result_line_phone(
                tool_name=tool_name,
                tool_args=tool_args,
                result_content=result_content,
                user_phone=self._user_phone,
            )
            if w1:
                warnings.append(w1)
            w2 = check_result_speed_test(
                tool_name=tool_name,
                tool_args=tool_args,
                result_content=result_content,
            )
            if w2:
                warnings.append(w2)
            w3 = check_result_can_send_mms(
                tool_name=tool_name,
                tool_args=tool_args,
                result_content=result_content,
                last_tool_results=self._last_tool_results,
                called_tools=self._called_all_tools,
            )
            if w3:
                warnings.append(w3)
            w4 = check_result_get_data_usage(
                tool_name=tool_name,
                tool_args=tool_args,
                result_content=result_content,
            )
            if w4:
                warnings.append(w4)
            w5 = check_result_check_network_status(
                tool_name=tool_name,
                tool_args=tool_args,
                result_content=result_content,
                called_tools=self._called_all_tools,
            )
            if w5:
                warnings.append(w5)
            w6 = check_result_line_suspended(
                tool_name=tool_name,
                tool_args=tool_args,
                result_content=result_content,
                called_tools=self._called_all_tools,
            )
            if w6:
                warnings.append(w6)
            return "\n".join(warnings) if warnings else None
        return None

    def is_user_impersonation(self, text: str) -> bool:
        """
        Detect when the user simulator has slipped out of character and is
        talking like the support agent (verifier #3).

        Symptoms observed in the retail run include the "user" turn:
          * confirming/summarising an action as if it were the agent
            ("your exchange has been processed", "will ship within ...");
          * offering further help ("is there anything else I can assist ...");
          * emitting a raw tool call / action JSON as plain text
            ("###TOOL_CALL###", '"action": "return_delivered_order_items"').

        Returns True when the text looks like agent/tool output rather than a
        customer utterance.
        """
        if not text or not isinstance(text, str):
            return False
        import re

        # Raw tool-call / action JSON leaking into a user turn.
        if re.search(r"###TOOL_CALL###", text, re.I):
            return True
        if re.search(r'"action(_input)?"\s*:', text) and re.search(
            r"(return|cancel|modify|exchange)_", text
        ):
            return True

        agent_markers = re.compile(
            r"(anything else I can (assist|help)"
            r"|is there anything else"
            r"|how can I (help|assist) you"
            r"|\(yes/no\)"
            r"|will ship within"
            r"|has been (processed|confirmed|completed|updated|cancelled|canceled)"
            r"|processed successfully"
            r"|shipped as requested"
            r"|your (new|order|return|exchange|refund).*(will ship|has been|is confirmed)"
            r"|I(?:'ve| have) (processed|completed|updated|confirmed|cancelled)"
            r"|refund .*(will be|has been) (issued|processed)"
            r"|(exchange|return|order|cancellation|modification|refund) "
            r"(has been |is )?(confirmed|processed|completed))",
            re.I,
        )
        return bool(agent_markers.search(text))

    def user_reminder_text(self) -> str | None:
        """
        Return a short in-character reminder for the user simulator, or ``None``
        once the per-conversation reminder budget is exhausted.
        """
        if self._user_reminder_count >= self.max_user_reminders:
            return None
        self._user_reminder_count += 1
        return (
            "REMINDER: You are the CUSTOMER, not the support agent. Stay in "
            "character. Do NOT confirm, summarise, or announce that actions "
            "have been completed, do NOT offer further assistance, and do NOT "
            "emit tool calls or action JSON. Only state, as the customer, what "
            "you want or answer the agent's question. Respond again as the "
            "customer."
        )

    def verify(
        self,
        tool_name: str,
        tool_args: dict,
        conversation: list[dict],
    ) -> str | None:
        """
        Check a tool call against policy rules.

        Parameters
        ----------
        tool_name : str
            Name of the tool being called.
        tool_args : dict
            Arguments passed to the tool.
        conversation : list[dict]
            Recent message history for SLM extraction.

        Returns
        -------
        str or None
            Feedback message if the call violates policy, None if allowed.
        """
        # Safety valve: if we've blocked this exact (tool, args) too many times, let it through
        _args_key = self._make_args_key(tool_name, tool_args)
        trace_mode = (
            self.domain == "retail"
            and os.getenv("TAU2_RETAIL_TRACE_VERIFIERS", "0") == "1"
        )
        if (
            not trace_mode
            and self._block_counts.get(_args_key, 0) >= self.max_feedback_per_tool
        ):
            logger.warning(
                "Safety valve: allowing %s after %d blocks (same args)",
                tool_name,
                self._block_counts[_args_key],
            )
            return None

        # Read tools: run read-specific rules (if available)
        if tool_name in self._read_tools:
            if self._check_read and not self.cheap_only:
                violation = self._check_read(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    conversation=conversation,
                    db=self.db,
                )
                if violation:
                    self._block_counts[_args_key] = self._block_counts.get(_args_key, 0) + 1
                    return f"[VERIFIER] {violation}"
            return None

        # Run policy checks
        violation = self._check_all(
            tool_name=tool_name,
            tool_args=tool_args,
            conversation=conversation,
            db=self.db,
            cheap_only=self.cheap_only,
            verifier=self,
        )

        if violation:
            self._block_counts[_args_key] = self._block_counts.get(_args_key, 0) + 1
            hint = self._get_corrective_hint(tool_name, tool_args)
            return f"[VERIFIER] {violation}" + (f"\n[HINT] {hint}" if hint else "")

        # Empirical retail checks derived from failed policy-run traces are
        # intentionally opt-in and kept separate from policy.md enforcement.
        if (
            not self.cheap_only
            and self.domain == "retail"
            and os.getenv("TAU2_RETAIL_TRACE_VERIFIERS", "0") == "1"
        ):
            from tau2.verifier.retail_trace_verifiers import check_all as check_traces

            trace_violation = check_traces(
                tool_name=tool_name,
                tool_args=tool_args,
                conversation=conversation,
                db=self.db,
                verifier=self,
            )
            if trace_violation:
                self._block_counts[_args_key] = self._block_counts.get(_args_key, 0) + 1
                return f"[VERIFIER] {trace_violation}"

        return None

    def _get_corrective_hint(self, tool_name: str, tool_args: dict) -> str | None:
        """
        Generate a corrective hint using DB state so the agent knows what to do instead.
        Returns None if no actionable hint can be generated.
        """
        try:
            if self.domain == "retail":
                return self._hint_retail(tool_name, tool_args)
            elif self.domain == "airline":
                return self._hint_airline(tool_name, tool_args)
            elif self.domain == "telecom":
                return self._hint_telecom(tool_name, tool_args)
        except Exception as e:
            logger.debug("Could not generate hint for %s: %s", tool_name, e)
        return None

    def _hint_retail(self, tool_name: str, tool_args: dict) -> str | None:
        order_id = tool_args.get("order_id", "")
        order = self.db.orders.get(order_id) if hasattr(self.db, 'orders') else None

        if tool_name in ("cancel_pending_order", "modify_pending_order_items",
                         "modify_pending_order_payment", "modify_pending_order_address"):
            if order and not order.status.startswith("pending"):
                return (
                    f"Order {order_id} has status '{order.status}'. "
                    f"This tool requires 'pending' status. "
                    f"If the user wants to return/exchange a delivered order, "
                    f"use return_delivered_order_items or exchange_delivered_order_items instead."
                )

        if tool_name == "return_delivered_order_items":
            payment_id = tool_args.get("payment_method_id", "")
            if order:
                user = self.db.users.get(order.user_id) if hasattr(self.db, 'users') else None
                if user:
                    # List valid refund destinations
                    orig_ids = {p.payment_method_id for p in order.payment_history}
                    gift_cards = [pid for pid, pm in user.payment_methods.items()
                                  if getattr(pm, 'source', '') == 'gift_card']
                    valid = list(orig_ids) + gift_cards
                    if payment_id not in valid and valid:
                        return (
                            f"Valid refund methods for this order: {valid}. "
                            f"The original payment was {list(orig_ids)}."
                        )

        if tool_name in ("modify_pending_order_items", "exchange_delivered_order_items"):
            # Check item count mismatch
            old_ids = tool_args.get("item_ids", [])
            new_ids = tool_args.get("new_item_ids", [])
            if len(old_ids) != len(new_ids):
                return (
                    f"You provided {len(old_ids)} items to replace but {len(new_ids)} new items. "
                    f"Must be 1-to-1. Provide exactly {len(old_ids)} new item(s)."
                )
            # Check product type mismatch — tell agent the correct product
            for old_id, new_id in zip(old_ids, new_ids):
                old_prod = None
                for p in self.db.products.values():
                    if old_id in p.variants:
                        old_prod = p
                        break
                if old_prod:
                    new_prod = None
                    for p in self.db.products.values():
                        if new_id in p.variants:
                            new_prod = p
                            break
                    if new_prod and old_prod.product_id != new_prod.product_id:
                        # List available variants of the correct product
                        avail = [vid for vid, v in old_prod.variants.items()
                                 if getattr(v, 'available', True) and vid != old_id]
                        hint = (
                            f"Item {old_id} is a '{old_prod.name}'. "
                            f"You must select a different variant of the same product."
                        )
                        if avail:
                            hint += f" Available variants: {avail[:8]}"
                        return hint
        return None

    def _hint_airline(self, tool_name: str, tool_args: dict) -> str | None:
        res_id = tool_args.get("reservation_id", "")
        reservation = None
        if hasattr(self.db, 'reservations'):
            reservation = self.db.reservations.get(res_id)

        if tool_name == "cancel_reservation" and reservation:
            # Check if cancellation conditions aren't met and explain what is allowed
            cabin = getattr(reservation, 'cabin', '')
            insurance = getattr(reservation, 'insurance', '')
            if cabin != 'business' and insurance != 'yes':
                return (
                    f"Reservation {res_id}: cabin='{cabin}', insurance='{insurance}'. "
                    f"Cancellation is only allowed if cabin is business class, "
                    f"within 24hrs of booking, or has insurance. "
                    f"TIP: You can first UPGRADE the cabin to business class using "
                    f"update_reservation_flights, then cancel. Or transfer to a human agent."
                )

        if tool_name == "update_reservation_flights" and reservation:
            # If route mismatch, tell agent the correct origin/destination
            origin = getattr(reservation, 'origin', '')
            dest = getattr(reservation, 'destination', '')
            ftype = getattr(reservation, 'flight_type', '')
            return (
                f"Reservation {res_id} route: {origin} → {dest} ({ftype}). "
                f"Search for flights that match this route. "
                f"Use search_direct_flight or search_onestop_flight with "
                f"origin='{origin}' and destination='{dest}'."
            )

        if tool_name == "book_reservation":
            # If route mismatch on booking, tell agent the correct airports
            origin = tool_args.get("origin", "")
            dest = tool_args.get("destination", "")
            ftype = tool_args.get("flight_type", "")
            return (
                f"The flights you selected don't match the route {origin} → {dest} ({ftype}). "
                f"Use search_direct_flight or search_onestop_flight with "
                f"origin='{origin}' and destination='{dest}' to find correct flights."
            )

        return None

    def _hint_telecom(self, tool_name: str, tool_args: dict) -> str | None:
        customer_id = tool_args.get("customer_id", "")
        line_id = tool_args.get("line_id", "")

        if tool_name == "refuel_data":
            gb = tool_args.get("gb_amount", 0)
            if gb > 2:
                return "Maximum data refuel per request is 2 GB. Split into multiple requests if needed."
            # Check line status
            if hasattr(self.db, 'customers'):
                cust = self.db.customers.get(customer_id)
                if cust and hasattr(cust, 'lines'):
                    line = cust.lines.get(line_id)
                    if line and getattr(line, 'status', '') != 'Active':
                        return (
                            f"Line {line_id} status is '{line.status}'. "
                            f"Must be 'Active' to refuel. Resume the line first with resume_line."
                        )

        if tool_name == "send_payment_request":
            bill_id = tool_args.get("bill_id", "")
            if hasattr(self.db, 'customers'):
                cust = self.db.customers.get(customer_id)
                if cust and hasattr(cust, 'bills'):
                    bill = cust.bills.get(bill_id)
                    if bill and getattr(bill, 'status', '') != 'Overdue':
                        return (
                            f"Bill {bill_id} status is '{bill.status}'. "
                            f"Payment requests can only be sent for 'Overdue' bills."
                        )
        return None

    #  Proactive read-tool annotations

    def annotate_read_result(self, tool_name: str, tool_args: dict, result_text: str) -> str | None:
        """
        After a successful read-tool call, return a short policy note to append
        to the tool result so the agent sees policy constraints *before* acting.

        Returns None if no annotation is warranted.
        """
        try:
            if self.domain == "retail":
                return self._annotate_retail(tool_name, tool_args, result_text)
            elif self.domain == "airline":
                return self._annotate_airline(tool_name, tool_args, result_text)
            elif self.domain == "telecom":
                return self._annotate_telecom(tool_name, tool_args, result_text)
        except Exception as e:
            logger.debug("annotate_read_result error for %s: %s", tool_name, e)
        return None

    def _annotate_retail(self, tool_name: str, tool_args: dict, result_text: str) -> str | None:
        if tool_name != "get_order_details":
            return None
        order_id = tool_args.get("order_id", "")
        order = self.db.orders.get(order_id) if hasattr(self.db, 'orders') else None
        if not order:
            return None

        notes: list[str] = []
        status = order.status
        if status == "pending":
            notes.append(
                f"[POLICY NOTE] Order {order_id} is 'pending'. "
                f"You may cancel (reasons: 'no longer needed' or 'ordered by mistake') "
                f"or modify items/payment/address. Items can only be modified once."
            )
        elif status.startswith("pending"):
            notes.append(
                f"[POLICY NOTE] Order {order_id} status is '{status}'. "
                f"Items have already been modified once — you CANNOT modify items again. "
                f"You may still cancel or modify payment/address."
            )
        elif status == "delivered":
            notes.append(
                f"[POLICY NOTE] Order {order_id} is 'delivered'. "
                f"You can ONLY use return_delivered_order_items or exchange_delivered_order_items. "
                f"Do NOT attempt cancel_pending_order or modify_pending_order_*."
            )
            # List valid refund methods
            user = self.db.users.get(order.user_id) if hasattr(self.db, 'users') else None
            if user:
                orig_ids = {p.payment_method_id for p in order.payment_history}
                gift_cards = [pid for pid, pm in user.payment_methods.items()
                              if getattr(pm, 'source', '') == 'gift_card']
                valid_refund = sorted(set(list(orig_ids) + gift_cards))
                if valid_refund:
                    notes.append(
                        f"[POLICY NOTE] Valid refund payment methods: {valid_refund}. "
                        f"Original payment: {sorted(orig_ids)}."
                    )
        elif status in ("shipped", "cancelled"):
            notes.append(
                f"[POLICY NOTE] Order {order_id} status is '{status}'. "
                f"No modifications are allowed."
            )
        return "\n".join(notes) if notes else None

    def _annotate_airline(self, tool_name: str, tool_args: dict, result_text: str) -> str | None:
        if tool_name != "get_reservation_details":
            return None
        res_id = tool_args.get("reservation_id", "")
        reservation = self.db.reservations.get(res_id) if hasattr(self.db, 'reservations') else None
        if not reservation:
            return None

        notes: list[str] = []
        cabin = getattr(reservation, 'cabin', 'unknown')
        insurance = getattr(reservation, 'insurance', 'no')
        membership = getattr(reservation, 'membership', 'regular')

        # Cancellation eligibility
        can_cancel_reasons: list[str] = []
        if cabin == "business":
            can_cancel_reasons.append("business class")
        if insurance == "yes":
            can_cancel_reasons.append("has travel insurance")
        # Check 24hr rule
        try:
            booked = getattr(reservation, 'booking_date', None)
            if booked:
                from datetime import datetime, timedelta
                CURRENT_TIME = datetime(2024, 5, 15, 15, 0, 0)
                booked_dt = datetime.strptime(booked, "%Y-%m-%d") if isinstance(booked, str) else booked
                if CURRENT_TIME - booked_dt < timedelta(hours=24):
                    can_cancel_reasons.append("within 24hrs of booking")
        except Exception:
            pass

        if can_cancel_reasons:
            notes.append(
                f"[POLICY NOTE] Reservation {res_id} CAN be cancelled ({', '.join(can_cancel_reasons)})."
            )
        else:
            notes.append(
                f"[POLICY NOTE] Reservation {res_id} CANNOT be cancelled — "
                f"cabin='{cabin}', insurance='{insurance}'. "
                f"Cancellation requires business class, travel insurance, or within 24hrs of booking. "
                f"If the user insists, transfer to a human agent."
            )

        # Baggage info
        from tau2.verifier.airline_policy_spec import _free_bags
        free = _free_bags(membership, cabin)
        notes.append(
            f"[POLICY NOTE] Free bags: {free} per passenger (membership={membership}, cabin={cabin}). "
            f"Max 2 extra paid bags per passenger at $50 each. Total max = {free + 2} per passenger."
        )

        # Basic economy restrictions
        if cabin == "basic_economy":
            notes.append(
                f"[POLICY NOTE] Basic economy: NO flight changes allowed, NO seat selection, "
                f"and NO upgrades."
            )

        return "\n".join(notes) if notes else None

    def _annotate_telecom(self, tool_name: str, tool_args: dict, result_text: str) -> str | None:
        if tool_name != "get_details_by_id":
            return None
        # Parse line and customer info from result
        # For telecom, the get_details_by_id tool returns comprehensive info
        notes: list[str] = []
        if "Suspended" in result_text:
            notes.append(
                "[POLICY NOTE] This line is 'Suspended'. "
                "To refuel data or enable services, resume the line first with resume_line."
            )
        if "Overdue" in result_text:
            notes.append(
                "[POLICY NOTE] Customer has Overdue bills. "
                "Use send_payment_request for overdue bills only."
            )
        if notes:
            return "\n".join(notes)
        return None

    def reset(self):
        """Reset all state (call between tasks)."""
        self._block_counts.clear()
        self._called_write_tools.clear()
        self._called_all_tools.clear()
        self._last_tool_results.clear()
        self._completed_actions.clear()
        self._called_user_tools.clear()
        self._expected_user_tools.clear()
        self._user_instructions = ""
        self._completion_nudge_count = 0
