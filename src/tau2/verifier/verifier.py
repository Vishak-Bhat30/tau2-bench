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
        self.domain = domain
        self.cheap_only = cheap_only
        self.max_feedback_per_tool = max_feedback_per_tool
        self.max_nudges = max_nudges

        # Track how many times we've blocked each tool (safety valve)
        self._block_counts: dict[str, int] = {}

        # Track which write tools have been successfully called
        self._called_write_tools: list[str] = []

        # Track completed actions with details (tool_name + summary of args)
        self._completed_actions: list[str] = []

        # Expected write tools for this task (set by classify_task)
        self._expected_tools: list[str] = []

        # How many nudges we've given
        self._nudge_count: int = 0

        # User instructions text (set by set_user_instructions)
        self._user_instructions: str = ""

        # Detailed task list extracted from user instructions (set by classify_task)
        self._task_list: list[str] = []

        # Track user-side tool calls (for telecom completion tracking)
        self._called_user_tools: list[str] = []

        # Expected user-side tools (for telecom)
        self._expected_user_tools: list[str] = []

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
            from tau2.verifier.telecom_policy_spec import check_all
            self._check_all = check_all
        else:
            raise ValueError(f"No policy spec for domain: {domain}")

    def set_user_instructions(self, instructions: str) -> None:
        """Store the user scenario instructions for use in classify_task and nudges."""
        self._user_instructions = instructions
        logger.info("User instructions set (%d chars)", len(instructions))

    def classify_task(self, conversation: list[dict]) -> None:
        """
        Classify the task based on user instructions + conversation.
        Uses the SLM on user instructions (much more reliable than conversation alone)
        to extract both the expected tools AND a detailed task list.
        """
        from tau2.verifier.slm_helper import slm_extract

        # Use user instructions if available (preferred), else fall back to conversation
        source = self._user_instructions if self._user_instructions else None

        if self.domain == "airline":
            mapping = {
                "book": "book_reservation",
                "cancel": "cancel_reservation",
                "modify_flights": "update_reservation_flights",
                "modify_baggage": "update_reservation_baggages",
                "modify_passengers": "update_reservation_passengers",
                "certificate": "send_certificate",
                "transfer": "transfer_to_human_agents",
            }
            actions_list = "book, cancel, modify_flights, modify_baggage, modify_passengers, certificate, transfer"
        elif self.domain == "retail":
            mapping = {
                "cancel_order": "cancel_pending_order",
                "modify_items": "modify_pending_order_items",
                "modify_payment": "modify_pending_order_payment",
                "modify_address": "modify_pending_order_address",
                "modify_user_address": "modify_user_address",
                "return_items": "return_delivered_order_items",
                "exchange_items": "exchange_delivered_order_items",
                "transfer": "transfer_to_human_agents",
            }
            actions_list = "cancel_order, modify_items, modify_payment, modify_address, modify_user_address, return_items, exchange_items, transfer"
        elif self.domain == "telecom":
            mapping = {
                "suspend_line": "suspend_line",
                "resume_line": "resume_line",
                "pay_bill": "send_payment_request",
                "refuel_data": "refuel_data",
                "enable_roaming": "enable_roaming",
                "disable_roaming": "disable_roaming",
                "transfer": "transfer_to_human_agents",
            }
            actions_list = "suspend_line, resume_line, pay_bill, refuel_data, enable_roaming, disable_roaming, transfer"
            # Also extract expected user-side actions for telecom
            user_mapping = {
                "toggle_airplane": "toggle_airplane_mode",
                "toggle_data_mode": "toggle_data",
                "set_network_preference": "set_network_mode_preference",
                "toggle_data_saver": "toggle_data_saver_mode",
                "disconnect_vpn": "disconnect_vpn",
                "reseat_sim": "reseat_sim_card",
                "grant_permission": "grant_app_permission",
                "toggle_roaming": "toggle_roaming",
                "reset_apn": "reset_apn_settings",
                "toggle_wifi_calling": "toggle_wifi_calling",
                "reboot": "reboot_device",
                "make_payment": "make_payment",
            }
        else:
            return

        if source:
            # Use user instructions directly for classification
            prompt = (
                f"Based on the user's scenario below, what actions need to be performed? "
                f"Pick ALL that apply from this list: {actions_list}. "
                f"If an action needs to be done on MULTIPLE orders/items, repeat it. "
                f"Answer with ONLY a comma-separated list.\n\n"
                f"User scenario:\n{source[:2000]}"
            )
            answer = slm_extract(prompt, [])  # empty conversation, question has the context
        else:
            prompt = (
                f"Based on the conversation, what does the user want to do? "
                f"Pick ALL that apply: {actions_list}. "
                f"Answer with ONLY a comma-separated list."
            )
            answer = slm_extract(prompt, conversation)

        raw = answer.lower().strip()
        self._expected_tools = []
        for key, tool_name in mapping.items():
            if key in raw:
                self._expected_tools.append(tool_name)

        # For telecom, also classify expected user-side actions
        if self.domain == "telecom" and source:
            user_actions_list = (
                "toggle_airplane, toggle_data_mode, set_network_preference, "
                "toggle_data_saver, disconnect_vpn, reseat_sim, grant_permission, "
                "toggle_roaming, reset_apn, toggle_wifi_calling, reboot, make_payment"
            )
            user_answer = slm_extract(
                f"Based on the user's scenario, what PHONE-SIDE troubleshooting actions "
                f"need to be performed on the user's device? "
                f"Pick ALL that apply from: {user_actions_list}. "
                f"These are actions the user does on their phone, not carrier-side actions. "
                f"Answer with ONLY a comma-separated list.\n\n"
                f"User scenario:\n{source[:2000]}",
                [],
            )
            user_raw = user_answer.lower().strip()
            self._expected_user_tools = []
            for key, tool_name in user_mapping.items():
                if key in user_raw:
                    self._expected_user_tools.append(tool_name)
            logger.info("Expected user tools: %s", self._expected_user_tools)

        # Also extract a detailed task list for better nudges
        if source:
            task_answer = slm_extract(
                "List ALL specific tasks the user wants done, as a numbered list. "
                "Be specific: include order IDs, item descriptions, addresses, etc. "
                "Example: '1. Cancel order #W1234 2. Return laptop from order #W5678'.\n\n"
                f"User scenario:\n{source[:2000]}",
                [],
                max_tokens=512,
            )
            self._task_list = [line.strip() for line in task_answer.strip().split("\n") if line.strip()]
        else:
            self._task_list = []

        logger.info("Task classified. Expected tools: %s, Task list: %s", self._expected_tools, self._task_list)

    def record_tool_call(self, tool_name: str, tool_args: dict | None = None) -> None:
        """Record that a write tool was successfully called (not blocked)."""
        if tool_name in self._write_tools:
            self._called_write_tools.append(tool_name)
            # Build a compact summary of what was done
            summary = self._summarize_action(tool_name, tool_args or {})
            self._completed_actions.append(summary)
            logger.info("Recorded action: %s", summary)

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

    def check_completion(self, conversation: list[dict]) -> str | None:
        """
        Check if the user's request is fully completed.

        Uses SLM to compare the user's task list against the completed actions.
        For each pending task, either nudges the agent to complete it or
        requires a strong justification for why it can't be done.

        Returns a nudge message if something is missing, None if complete.
        """
        if self._nudge_count >= self.max_nudges:
            logger.info("Max nudges reached (%d), not nudging", self.max_nudges)
            return None

        if not self._expected_tools:
            return None

        # For telecom, include user-side tool calls in the "work done" check
        all_called = self._called_write_tools + self._called_user_tools
        all_expected = self._expected_tools + self._expected_user_tools

        real_writes = [t for t in all_called if t != "transfer_to_human_agents"]
        non_transfer = [t for t in all_expected if t != "transfer_to_human_agents"]

        # If no write tools called and we expect non-certificate actions, nudge aggressively
        # (skip this for certificate-only tasks where the user may not actually want one)
        non_cert_expected = [t for t in non_transfer if t != "send_certificate"]
        if not real_writes and non_cert_expected:
            self._nudge_count += 1
            if self._task_list:
                task_str = "\n".join(self._task_list)
                nudge = (
                    f"STOP \u2014 the user's request is NOT complete. You haven't performed any actions yet. "
                    f"Here are the tasks the user requested:\n{task_str}\n\n"
                    f"You MUST attempt each task above using the appropriate tool call. "
                    f"Do not ask for further confirmation \u2014 proceed directly."
                )
            else:
                tool_descriptions = {
                    "book_reservation": "book the reservation",
                    "cancel_reservation": "cancel the reservation(s)",
                    "update_reservation_flights": "update the flights",
                    "update_reservation_baggages": "update the baggage",
                    "update_reservation_passengers": "update the passengers",
                    "send_certificate": "send the certificate",
                    "cancel_pending_order": "cancel the order",
                    "modify_pending_order_items": "modify the order items",
                    "modify_pending_order_payment": "modify the payment method",
                    "modify_pending_order_address": "modify the shipping address",
                    "modify_user_address": "update the user's default address",
                    "return_delivered_order_items": "return the item(s)",
                    "exchange_delivered_order_items": "exchange the item(s)",
                    "suspend_line": "suspend the line",
                    "resume_line": "resume the line",
                    "send_payment_request": "send the payment request",
                    "refuel_data": "add data to the line",
                    "enable_roaming": "enable roaming",
                    "disable_roaming": "disable roaming",
                }
                missing_descs = [tool_descriptions.get(t, t) for t in non_cert_expected]
                nudge = (
                    f"STOP \u2014 the user's request is NOT complete. You haven't performed any actions yet. "
                    f"You still need to: {', '.join(missing_descs)}. "
                    f"Proceed now. Do not ask for further confirmation."
                )
            logger.info("Completion nudge #%d: %s", self._nudge_count, nudge)
            return nudge

        # If all expected (non-transfer) tools have been called, skip SLM check
        expected_set = set(non_transfer)
        called_set = set(real_writes)
        if expected_set and expected_set.issubset(called_set):
            logger.info("All expected tools called (%s), skipping SLM nudge check", expected_set)
            return None

        # Some writes were made but not all — do a detailed task-by-task SLM check
        from tau2.verifier.slm_helper import slm_extract

        # Build a summary of completed actions
        if self._completed_actions:
            actions_done = "\n".join(f"  - {a}" for a in self._completed_actions)
        else:
            actions_done = "  (none)"

        # Build task list for SLM
        if self._task_list:
            task_str = "\n".join(self._task_list)
        elif self._user_instructions:
            task_str = self._user_instructions[:1500]
        else:
            task_str = "(not available)"

        answer = slm_extract(
            f"The user requested these tasks:\n{task_str}\n\n"
            f"The agent has completed these actions:\n{actions_done}\n\n"
            f"Go through each user task ONE BY ONE and check if it has been "
            f"completed by the actions above. For each task, respond with either:\n"
            f"  DONE: <task description>\n"
            f"  PENDING: <task description>\n\n"
            f"If ALL tasks are done, just say 'ALL_COMPLETE'.\n"
            f"A task is DONE if ANY of these apply:\n"
            f"  (a) there is a matching action above, OR\n"
            f"  (b) the agent already explained to the user in conversation why "
            f"the action cannot or should not be done (e.g. policy prevents it, "
            f"user said they don't want it, user is not eligible), OR\n"
            f"  (c) the task is about communicating information or explaining something "
            f"and the agent addressed it in conversation.\n"
            f"Mark PENDING only if the agent has NOT addressed the task at all — "
            f"neither by action NOR by explanation in conversation.",
            conversation,
            max_tokens=512,
        )
        result = answer.strip()

        if "ALL_COMPLETE" in result.upper() or "all_complete" in result.lower():
            return None

        # Check if there are PENDING items
        pending_lines = []
        for line in result.split("\n"):
            line = line.strip()
            if line.upper().startswith("PENDING"):
                pending_lines.append(line)

        if not pending_lines:
            # SLM didn't find anything pending — also check for "DONE" everywhere
            done_count = result.upper().count("DONE")
            pending_count = result.upper().count("PENDING")
            if done_count > 0 and pending_count == 0:
                return None
            # Ambiguous — treat as possible incomplete
            if "complete" in result.lower() or "done" in result.lower():
                return None

        # There are pending tasks — nudge the agent
        self._nudge_count += 1
        pending_str = "\n".join(pending_lines) if pending_lines else result

        nudge = (
            f"WAIT — your work is not complete. The following tasks are still pending:\n"
            f"{pending_str}\n\n"
            f"For each pending task, you MUST either:\n"
            f"1. Complete it now using the appropriate tool call, OR\n"
            f"2. Explain clearly to the user WHY it cannot be done "
            f"(cite the specific policy rule or system limitation that prevents it).\n\n"
            f"Do not end the conversation until all tasks are addressed."
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
                    self._block_counts[tool_name] = self._block_counts.get(tool_name, 0) + 1
                    return f"[VERIFIER] {violation}"
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

        # Additional item-level validation using user instructions (retail/airline)
        if self._user_instructions and not self.cheap_only:
            item_violation = self._check_item_args(tool_name, tool_args, conversation)
            if item_violation:
                self._block_counts[tool_name] = self._block_counts.get(tool_name, 0) + 1
                return f"[VERIFIER] {item_violation}"

        return None

    def _check_item_args(self, tool_name: str, tool_args: dict, conversation: list[dict]) -> str | None:
        """
        Validate item-level arguments using user instructions + DB.
        For modify/exchange tools, check that the new items match
        what the user actually described in their scenario.
        """
        # Only for retail tools that deal with item selection
        item_tools = {
            "modify_pending_order_items",
            "exchange_delivered_order_items",
        }
        if tool_name not in item_tools:
            return None

        new_item_ids = tool_args.get("new_item_ids", [])
        if not new_item_ids:
            return None

        from tau2.verifier.slm_helper import slm_extract

        # Ask SLM what features the user wants for the new items
        user_wants = slm_extract(
            "Based on the user's scenario, what specific features/attributes does "
            "the user want for the NEW item(s) they are exchanging/modifying to? "
            "List the desired attributes (color, size, material, capacity, etc.) "
            "Be precise — only include what the user explicitly stated.\n\n"
            f"User scenario:\n{self._user_instructions[:1500]}",
            [],
            max_tokens=256,
        )

        if not user_wants.strip():
            return None

        # Build a description of what the agent is actually selecting
        item_descriptions = []
        for nid in new_item_ids:
            desc = f"item {nid}"
            for product in self.db.products.values():
                if hasattr(product, 'variants') and nid in product.variants:
                    variant = product.variants[nid]
                    options = getattr(variant, 'options', {})
                    desc = f"{product.name} ({nid}): {options}, price=${getattr(variant, 'price', '?')}"
                    break
            item_descriptions.append(desc)

        items_str = "; ".join(item_descriptions)

        # Ask SLM if the selected items match what user wants
        match_answer = slm_extract(
            f"The user wants these features for the new item(s): {user_wants}\n\n"
            f"The agent selected these items: {items_str}\n\n"
            f"Do the selected items match what the user wants? "
            f"Check each attribute the user specified. "
            f"Answer 'yes' if they match, or describe the mismatch.",
            [],
        )

        result = match_answer.lower().strip()
        if result.startswith("yes"):
            return None

        return (
            f"Argument mismatch: the selected items don't match what the user requested. "
            f"User wants: {user_wants.strip()}. "
            f"You selected: {items_str}. "
            f"Issue: {match_answer.strip()}. "
            f"Please select the correct item variant(s)."
        )

    def reset(self):
        """Reset all state (call between tasks)."""
        self._block_counts.clear()
        self._called_write_tools.clear()
        self._expected_tools.clear()
        self._called_user_tools.clear()
        self._expected_user_tools.clear()
        self._nudge_count = 0
        self._user_instructions = ""
        self._task_list = []
