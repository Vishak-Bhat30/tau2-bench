"""
PolicyVerifier — intercepts tool calls in the orchestrator and checks them
against the airline policy spec before execution.

Also provides "completion nudge" functionality: at the start of a task, it
uses the SLM to classify what kind of task this is and what write tools are
expected.  When the user says STOP but the required tools haven't been called,
the orchestrator can ask the verifier for a nudge message to send to the agent.

Usage:
    verifier = PolicyVerifier(db=flight_db, domain="airline")
    verifier.classify_task(conversation)          # call once at start
    result = verifier.verify(tool_call, conversation)
    nudge = verifier.check_completion(conversation) # call when user says stop
"""

from __future__ import annotations

import logging
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
        self.domain = domain
        self.cheap_only = cheap_only
        self.max_feedback_per_tool = max_feedback_per_tool
        self.max_nudges = max_nudges

        # Track how many times we've blocked each tool (safety valve)
        self._block_counts: dict[str, int] = {}

        # Track which write tools have been successfully called
        self._called_write_tools: list[str] = []

        # Expected write tools for this task (set by classify_task)
        self._expected_tools: list[str] = []

        # How many nudges we've given
        self._nudge_count: int = 0

        # Domain-specific tool sets
        self._write_tools = WRITE_TOOLS_BY_DOMAIN.get(domain, set())
        self._read_tools = READ_TOOLS_BY_DOMAIN.get(domain, set())

        # Load the appropriate spec module
        if domain == "airline":
            from tau2.verifier.airline_policy_spec import check_all
            self._check_all = check_all
        elif domain == "retail":
            from tau2.verifier.retail_policy_spec import check_all
            self._check_all = check_all
        elif domain == "telecom":
            from tau2.verifier.telecom_policy_spec import check_all
            self._check_all = check_all
        else:
            raise ValueError(f"No policy spec for domain: {domain}")

    def classify_task(self, conversation: list[dict]) -> None:
        """
        Classify the task based on conversation to determine expected write tools.
        Call this once early in the conversation (after first user message).
        """
        from tau2.verifier.slm_helper import slm_extract

        if self.domain == "airline":
            prompt = (
                "Based on the conversation, what does the user want to do? "
                "Pick ALL that apply from this list: "
                "book, cancel, modify_flights, modify_baggage, modify_passengers, "
                "certificate, transfer. "
                "Answer with ONLY a comma-separated list of the applicable actions."
            )
            mapping = {
                "book": "book_reservation",
                "cancel": "cancel_reservation",
                "modify_flights": "update_reservation_flights",
                "modify_baggage": "update_reservation_baggages",
                "modify_passengers": "update_reservation_passengers",
                "certificate": "send_certificate",
                "transfer": "transfer_to_human_agents",
            }
        elif self.domain == "retail":
            prompt = (
                "Based on the conversation, what does the user want to do? "
                "Pick ALL that apply from this list: "
                "cancel_order, modify_items, modify_payment, modify_address, "
                "return_items, exchange_items, transfer. "
                "Answer with ONLY a comma-separated list of the applicable actions."
            )
            mapping = {
                "cancel_order": "cancel_pending_order",
                "modify_items": "modify_pending_order_items",
                "modify_payment": "modify_pending_order_payment",
                "modify_address": "modify_pending_order_address",
                "return_items": "return_delivered_order_items",
                "exchange_items": "exchange_delivered_order_items",
                "transfer": "transfer_to_human_agents",
            }
        elif self.domain == "telecom":
            prompt = (
                "Based on the conversation, what does the user want to do? "
                "Pick ALL that apply from this list: "
                "suspend_line, resume_line, pay_bill, refuel_data, "
                "enable_roaming, disable_roaming, transfer. "
                "Answer with ONLY a comma-separated list of the applicable actions."
            )
            mapping = {
                "suspend_line": "suspend_line",
                "resume_line": "resume_line",
                "pay_bill": "send_payment_request",
                "refuel_data": "refuel_data",
                "enable_roaming": "enable_roaming",
                "disable_roaming": "disable_roaming",
                "transfer": "transfer_to_human_agents",
            }
        else:
            return

        answer = slm_extract(prompt, conversation)
        raw = answer.lower().strip()
        self._expected_tools = []
        for key, tool_name in mapping.items():
            if key in raw:
                self._expected_tools.append(tool_name)

        logger.info("Task classified. Expected tools: %s", self._expected_tools)

    def record_tool_call(self, tool_name: str) -> None:
        """Record that a write tool was successfully called (not blocked)."""
        if tool_name in self._write_tools:
            self._called_write_tools.append(tool_name)

    def check_completion(self, conversation: list[dict]) -> str | None:
        """
        Check if the user's request is fully completed.
        Uses the SLM to ask whether all requested actions were performed,
        based on the conversation (which includes tool call results).
        Returns a nudge message if something is missing, None if complete.
        """
        if self._nudge_count >= self.max_nudges:
            logger.info("Max nudges reached (%d), not nudging", self.max_nudges)
            return None

        if not self._expected_tools:
            return None

        # Quick check: if no real write tools called at all, definitely nudge
        real_writes = [t for t in self._called_write_tools if t != "transfer_to_human_agents"]
        if not real_writes:
            # Don't nudge if the only expected action is transfer
            non_transfer = [t for t in self._expected_tools if t != "transfer_to_human_agents"]
            if not non_transfer:
                return None

            self._nudge_count += 1
            tool_descriptions = {
                # airline
                "book_reservation": "book the reservation",
                "cancel_reservation": "cancel the reservation(s)",
                "update_reservation_flights": "update the flights",
                "update_reservation_baggages": "update the baggage",
                "update_reservation_passengers": "update the passengers",
                "send_certificate": "send the certificate",
                # retail
                "cancel_pending_order": "cancel the order",
                "modify_pending_order_items": "modify the order items",
                "modify_pending_order_payment": "modify the payment method",
                "modify_pending_order_address": "modify the shipping address",
                "return_delivered_order_items": "return the item(s)",
                "exchange_delivered_order_items": "exchange the item(s)",
                # telecom
                "suspend_line": "suspend the line",
                "resume_line": "resume the line",
                "send_payment_request": "send the payment request",
                "refuel_data": "add data to the line",
                "enable_roaming": "enable roaming",
                "disable_roaming": "disable roaming",
            }
            missing_descs = [tool_descriptions.get(t, t) for t in non_transfer]
            nudge = (
                f"The user's request is not complete yet. You haven't performed any actions. "
                f"You still need to: {', '.join(missing_descs)}. "
                f"Please proceed with the required action(s) now using the appropriate tool call(s). "
                f"Do not ask for further confirmation — the user has already provided all needed information."
            )
            logger.info("Completion nudge #%d: %s", self._nudge_count, nudge)
            return nudge

        # Some writes were made — use SLM to check if everything is done
        from tau2.verifier.slm_helper import slm_extract
        answer = slm_extract(
            "Based on the conversation, has the agent fully completed ALL of the user's requests? "
            "Consider: Did they book all needed reservations? Cancel all requested reservations? "
            "Update all requested flights/baggage/passengers? "
            "If something is still pending or was only partially done, describe what's missing. "
            "Answer 'complete' if everything is done, or describe what's still missing.",
            conversation,
        )
        result = answer.lower().strip()

        if result in ("complete", "yes", "done"):
            return None

        # SLM says something is missing
        self._nudge_count += 1
        nudge = (
            f"The user's request is not fully complete. {answer.strip()} "
            f"Please proceed with the remaining action(s) now using the appropriate tool call(s). "
            f"Do not ask for confirmation — proceed directly."
        )
        logger.info("Completion nudge #%d: %s", self._nudge_count, nudge)
        return nudge

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
        # Safety valve: if we've blocked this tool too many times, let it through
        if self._block_counts.get(tool_name, 0) >= self.max_feedback_per_tool:
            logger.warning(
                "Safety valve: allowing %s after %d blocks",
                tool_name,
                self._block_counts[tool_name],
            )
            return None

        # Read tools don't need policy checks
        if tool_name in self._read_tools:
            return None

        # Run policy checks
        violation = self._check_all(
            tool_name=tool_name,
            tool_args=tool_args,
            conversation=conversation,
            db=self.db,
            cheap_only=self.cheap_only,
        )

        if violation:
            self._block_counts[tool_name] = self._block_counts.get(tool_name, 0) + 1
            return f"[VERIFIER] {violation}"

        return None

    def reset(self):
        """Reset all state (call between tasks)."""
        self._block_counts.clear()
        self._called_write_tools.clear()
        self._expected_tools.clear()
        self._nudge_count = 0
