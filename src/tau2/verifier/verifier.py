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

        # Track how many times we've blocked each (tool, args) pair (safety valve)
        # Key = (tool_name, frozenset of arg items) so same call+args bypasses after N blocks
        self._block_counts: dict[tuple, int] = {}

        # Track which write tools have been successfully called
        self._called_write_tools: list[str] = []

        # Track ALL tool calls (including reads) for pre-condition checks
        self._called_all_tools: list[str] = []

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

    def set_user_instructions(self, instructions: str) -> None:
        """Store the user scenario instructions for use in classify_task and nudges."""
        self._user_instructions = instructions
        logger.info("User instructions set (%d chars)", len(instructions))

    @staticmethod
    def _make_args_key(tool_name: str, tool_args: dict) -> tuple:
        """Create a hashable key from (tool_name, args) for the safety-valve counter."""
        try:
            frozen = frozenset(sorted((k, str(v)) for k, v in tool_args.items()))
        except Exception:
            frozen = frozenset()
        return (tool_name, frozen)

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
                f"Based on the user's scenario below, what WRITE actions need to be performed? "
                f"Pick ALL that apply from this list: {actions_list}. "
                f"ONLY include actions that CHANGE data (booking, cancelling, modifying, updating). "
                f"Do NOT include actions where the user just asks a QUESTION or wants INFORMATION "
                f"(e.g. 'how many bags can I bring?', 'what's my balance?', 'is my flight delayed?'). "
                f"If an action needs to be done on MULTIPLE items, repeat it. "
                f"If NO write actions are needed (information-only request), answer 'none'. "
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
        # Handle "none" / info-only responses
        if raw in ("none", "no actions", "no write actions", "information only"):
            logger.info("Task classified as info-only (no write actions expected)")
        else:
            # Split by comma and match each token to count repeated actions
            # (e.g. "cancel, cancel, cancel" → 3 cancel_reservation entries)
            tokens = [t.strip() for t in raw.split(",") if t.strip()]
            for token in tokens:
                for key, tool_name in mapping.items():
                    if key in token:
                        self._expected_tools.append(tool_name)
                        break  # only match first mapping per token

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
                "List ALL specific ACTIONS the user wants done, as a numbered list. "
                "ONLY include positive actions that require a tool call (booking, cancelling, "
                "modifying, updating, etc.). "
                "Do NOT include instructions about what the agent should NOT do, "
                "what to refuse, what to deny, or behavioral constraints. "
                "Do NOT include information-gathering steps (like 'look up reservation'). "
                "Be specific: include order IDs, item descriptions, addresses, etc. "
                "Example: '1. Cancel order #W1234 2. Return laptop from order #W5678'.\n\n"
                f"User scenario:\n{source[:2000]}",
                [],
                max_tokens=512,
            )
            raw_tasks = [line.strip() for line in task_answer.strip().split("\n") if line.strip()]
            # Filter out prohibition/negative tasks that leak test instructions
            _NEG_MARKERS = (
                "do not", "don't", "never", "under no circumstances",
                "should not", "refuse", "deny", "must not", "cannot",
                "will not", "not allow", "not permitted",
            )
            self._task_list = [
                t for t in raw_tasks
                if not any(marker in t.lower() for marker in _NEG_MARKERS)
            ]
            if len(raw_tasks) != len(self._task_list):
                logger.info(
                    "Filtered %d prohibition tasks from task list (kept %d)",
                    len(raw_tasks) - len(self._task_list), len(self._task_list),
                )
        else:
            self._task_list = []

        logger.info("Task classified. Expected tools: %s, Task list: %s", self._expected_tools, self._task_list)

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

    def check_completion(self, conversation: list[dict]) -> str | None:
        """
        Decide whether it is safe to let the conversation stop.

        Called by the orchestrator when the user emits a stop signal
        (###STOP###). This guards against two failure modes seen in the retail
        run:

          * premature stop — the user says "yes" and immediately stops before
            the agent has actually executed the confirmed write (verifier #1);
          * abandoned confirmation — the user stops while an expected write
            action still has not been performed (verifier #5).

        In both cases we return an agent-directed nudge asking it to finish the
        outstanding write(s); the orchestrator forwards this instead of
        stopping. Returns ``None`` (allow the stop) when there is nothing left
        to do.
        """
        # Only nudge a bounded number of times so we can never loop forever.
        if self._nudge_count >= self.max_nudges:
            logger.info("Max nudges reached (%d), allowing stop", self.max_nudges)
            return None

        # No write actions were ever expected (info-only task) -> safe to stop.
        if not self._expected_tools and not self._expected_user_tools:
            return None

        # A transfer to a human is itself a valid resolution -> safe to stop.
        if "transfer_to_human_agents" in self._called_write_tools:
            return None

        # Prerequisite guard: only nudge once the agent has actually established
        # context (a successful user/order/customer lookup). If the agent is
        # still stuck gathering info (e.g. identity verification failed), pushing
        # it to "execute now" is counter-productive and just adds noise, so we
        # allow the stop instead.
        _LOOKUP_TOOLS = {
            "retail": {
                "find_user_id_by_email", "find_user_id_by_name_zip",
                "get_order_details", "get_user_details",
            },
            "airline": {"get_user_details", "get_reservation_details"},
            "telecom": {
                "get_customer_by_phone", "get_customer_by_id",
                "get_customer_by_name", "get_details_by_id",
            },
        }.get(self.domain, set())
        if _LOOKUP_TOOLS and not (_LOOKUP_TOOLS & set(self._called_all_tools)):
            logger.info(
                "No successful context lookup yet (%s); allowing stop without nudge",
                self.domain,
            )
            return None

        # Compare expected vs. actually-executed write tools (count-aware so
        # multi-action tasks like "cancel two orders" are handled correctly).
        from collections import Counter

        expected = Counter(self._expected_tools) + Counter(self._expected_user_tools)
        called = Counter(self._called_write_tools) + Counter(self._called_user_tools)

        pending: list[str] = []
        for tool, need in expected.items():
            missing = need - called.get(tool, 0)
            for _ in range(max(0, missing)):
                pending.append(tool)

        if not pending:
            # Everything the task required has been executed -> safe to stop.
            return None

        # There is still outstanding work — build a specific, actionable nudge.
        self._nudge_count += 1
        tool_descriptions = {
            "cancel_pending_order": "cancel the pending order",
            "modify_pending_order_items": "modify the order items",
            "modify_pending_order_payment": "change the payment method",
            "modify_pending_order_address": "change the shipping address",
            "modify_user_address": "update the user's default address",
            "return_delivered_order_items": "return the item(s)",
            "exchange_delivered_order_items": "exchange the item(s)",
            "book_reservation": "book the reservation",
            "cancel_reservation": "cancel the reservation(s)",
            "update_reservation_flights": "update the flights",
            "update_reservation_baggages": "update the baggage",
            "update_reservation_passengers": "update the passengers",
            "send_certificate": "send the certificate",
            "suspend_line": "suspend the line",
            "resume_line": "resume the line",
            "send_payment_request": "send the payment request",
            "refuel_data": "add data to the line",
            "enable_roaming": "enable roaming",
            "disable_roaming": "disable roaming",
        }
        missing_descs = [tool_descriptions.get(t, t) for t in pending]
        if self._completed_actions:
            actions_done = "\n".join(f"  - {a}" for a in self._completed_actions)
        else:
            actions_done = "  (none yet)"

        nudge = (
            "Do not end the conversation yet — the customer's request is not "
            "fully carried out.\n\n"
            f"Actions completed so far:\n{actions_done}\n\n"
            f"Still outstanding: {', '.join(missing_descs)}.\n\n"
            "Execute the outstanding action(s) now with the appropriate tool "
            "call. If you already asked for confirmation and the customer "
            "agreed, proceed with the write immediately. Once every action is "
            "done, ask the customer if there is anything else before finishing."
        )
        logger.info("Completion nudge #%d: %s", self._nudge_count, nudge)
        return nudge

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
        if self._block_counts.get(_args_key, 0) >= self.max_feedback_per_tool:
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

        if self._user_instructions and not self.cheap_only and self.domain == "retail" and self._slm_block:
            item_violation = self._check_item_args(tool_name, tool_args, conversation)
            if item_violation:
                self._block_counts[_args_key] = self._block_counts.get(_args_key, 0) + 1
                return f"[VERIFIER] {item_violation}"

        if self._user_instructions and not self.cheap_only and self.domain == "retail" and self._slm_block:
            arg_violation = self._check_tool_args(tool_name, tool_args, conversation)
            if arg_violation:
                self._block_counts[_args_key] = self._block_counts.get(_args_key, 0) + 1
                hint = self._get_corrective_hint(tool_name, tool_args)
                return f"[VERIFIER] {arg_violation}" + (f"\n[HINT] {hint}" if hint else "")

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
            "Be precise — only include what the user explicitly stated. "
            "If the user did NOT specify any attributes, answer ONLY 'none'.\n\n"
            f"User scenario:\n{self._user_instructions[:1500]}",
            conversation,
            max_tokens=256,
        )

        if not user_wants.strip():
            return None

        # If the user didn't specify attributes, skip validation entirely
        wants_lower = user_wants.lower().strip()
        _NO_ATTR_MARKERS = (
            "none", "no specific", "did not explicitly", "not specified",
            "no attributes", "not explicitly state", "no desired attributes",
            "did not specify", "no particular", "not mentioned",
        )
        if any(marker in wants_lower for marker in _NO_ATTR_MARKERS):
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
            conversation,
        )

        result = match_answer.lower().strip()
        if result.startswith("yes"):
            return None
        # Accept verbose affirmative answers
        _MATCH_MARKERS = ("match", "correct", "consistent", "align", "appropriate")
        if any(m in result for m in _MATCH_MARKERS) and "mismatch" not in result and "don't match" not in result and "incorrect" not in result:
            return None

        return (
            f"Argument mismatch: the selected items don't match what the user requested. "
            f"User wants: {user_wants.strip()}. "
            f"You selected: {items_str}. "
            f"Issue: {match_answer.strip()}. "
            f"Please select the correct item variant(s)."
        )

    # key args to validate per tool (domain-agnostic)
    # Only ID-type args that the SLM can reliably verify (no amounts/values).
    _KEY_ARGS_BY_TOOL: dict[str, list[str]] = {
        # Airline
        "book_reservation": ["user_id"],
        "cancel_reservation": ["reservation_id"],
        "update_reservation_flights": ["reservation_id"],
        "update_reservation_baggages": ["reservation_id"],
        "update_reservation_passengers": ["reservation_id"],
        "send_certificate": ["reservation_id"],
        # Retail
        "cancel_pending_order": ["order_id"],
        "modify_pending_order_items": ["order_id"],
        "modify_pending_order_payment": ["order_id"],
        "modify_pending_order_address": ["order_id"],
        "return_delivered_order_items": ["order_id"],
        "exchange_delivered_order_items": ["order_id"],
        "modify_user_address": ["user_id"],
        # Telecom
        "suspend_line": ["customer_id", "line_id"],
        "resume_line": ["customer_id", "line_id"],
        "send_payment_request": ["customer_id", "bill_id"],
        "refuel_data": ["customer_id", "line_id"],
    }

    def _check_tool_args(self, tool_name: str, tool_args: dict, conversation: list[dict]) -> str | None:
        """
        General argument validation using SLM + user scenario.

        Only validates ID-type arguments (order_id, reservation_id, etc.)
        that the SLM can reliably extract from the user scenario.
        Does NOT validate amounts, items, or other values that require
        deeper reasoning (those are handled by domain-specific rules).
        """
        # Only check tools we have key-arg definitions for
        key_args = self._KEY_ARGS_BY_TOOL.get(tool_name)
        if not key_args:
            return None

        # Skip transfer_to_human_agents — no args to validate
        if tool_name == "transfer_to_human_agents":
            return None

        import json as _json
        from tau2.verifier.slm_helper import slm_extract

        # Build a representation of the actual ID args being passed
        actual = {k: tool_args.get(k) for k in key_args if tool_args.get(k) is not None}
        if not actual:
            return None
        actual_str = _json.dumps(actual, default=str)

        # Quick check: if ALL ID values already appeared in conversation
        # (tool results, user messages, etc.), they were discovered via lookup — trust them.
        conv_text = " ".join(m.get("content", "") for m in conversation)
        if all(str(v) in conv_text for v in actual.values()):
            return None  # All IDs appeared in conversation — trust the agent

        # Ask SLM to validate IDs against the user scenario + conversation
        prompt = (
            f"The agent is calling tool `{tool_name}` with these ID arguments:\n"
            f"{actual_str}\n\n"
            f"Based on the user scenario AND the full conversation history, "
            f"are these IDs correct? Only check IDs — ignore amounts and other values.\n"
            f"IMPORTANT: The user may have asked for actions on MULTIPLE orders/reservations. "
            f"An ID is correct if it appears ANYWHERE in the conversation or was discovered "
            f"via tool lookups, even if it's not in the original user scenario.\n\n"
            f"User scenario:\n{self._user_instructions[:1500]}\n\n"
            f"If the IDs are correct, answer ONLY 'yes'.\n"
            f"If an ID is wrong, answer: 'wrong: <param_name> should be <correct_value> not <wrong_value>'"
        )
        answer = slm_extract(prompt, conversation, max_tokens=256)

        result = answer.lower().strip()
        if result.startswith("yes"):
            return None

        # Accept verbose "correct" answers that don't start with "yes"
        _PASS_MARKERS = ("correct", "match", "right", "valid", "straightforward", "confirms")
        if any(m in result for m in _PASS_MARKERS) and "wrong" not in result and "incorrect" not in result:
            return None

        # Only act on "wrong:" answers to avoid false positives
        if "wrong" not in result:
            return None

        return (
            f"Argument mismatch: {answer.strip()}. "
            f"You called `{tool_name}` with {actual_str}. "
            f"Please check the user's request and use the correct arguments."
        )

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
        self._expected_tools.clear()
        self._called_user_tools.clear()
        self._expected_user_tools.clear()
        self._nudge_count = 0
        self._user_instructions = ""
        self._task_list = []
