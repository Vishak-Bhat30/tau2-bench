"""
Telecom Policy Spec — verifiable rules extracted from main_policy_solo.md
and tech_support_workflow_solo.md.

Each rule is a function that takes:
  - tool_name: str           (the tool being called)
  - tool_args: dict          (the arguments passed to the tool)
  - conversation: list[dict] (recent message history for SLM extraction)
  - db: TelecomDB            (current database state for lookups)

And returns:
  - None            if the call is ALLOWED (rule passes or doesn't apply)
  - str             a feedback message explaining the violation
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Simulated date from telecom/utils.py
CURRENT_DATE = datetime.date(2025, 2, 25)


# ============================================================================
#  Helpers
# ============================================================================

def _find_customer(db, customer_id: str):
    """Find customer by ID from the list-based TelecomDB."""
    for c in db.customers:
        if c.customer_id == customer_id:
            return c
    return None


def _find_line(db, line_id: str):
    """Find line by ID."""
    for line in db.lines:
        if line.line_id == line_id:
            return line
    return None


def _find_bill(db, bill_id: str):
    """Find bill by ID."""
    for bill in db.bills:
        if bill.bill_id == bill_id:
            return bill
    return None


def _find_plan(db, plan_id: str):
    """Find plan by ID."""
    for plan in db.plans:
        if plan.plan_id == plan_id:
            return plan
    return None


def _get_customer_bills(db, customer_id: str):
    """Get all bills for a customer."""
    customer = _find_customer(db, customer_id)
    if not customer:
        return []
    return [_find_bill(db, bid) for bid in customer.bill_ids if _find_bill(db, bid)]


def _has_overdue_bills(db, customer_id: str) -> bool:
    """Check if customer has any overdue bills."""
    for bill in _get_customer_bills(db, customer_id):
        if bill and bill.status.value == "Overdue":
            return True
    return False


def _has_awaiting_payment_bill(db, customer_id: str) -> bool:
    """Check if customer already has a bill in AWAITING PAYMENT status."""
    for bill in _get_customer_bills(db, customer_id):
        if bill and bill.status.value == "Awaiting Payment":
            return True
    return False


# ============================================================================
#  REFUEL DATA rules
#  Policy: "The maximum amount of data that can be refueled is 2GB."
#  Policy: Line must be active to refuel.
#  Policy: "Know how much data they want to refuel" / "Confirm the price"
# ============================================================================

def rule_refuel_max_2gb(tool_name, tool_args, conversation, db):
    """Data refueling is capped at 2 GB per request."""
    if tool_name != "refuel_data":
        return None
    gb_amount = tool_args.get("gb_amount", 0)
    try:
        gb_amount = float(gb_amount)
    except (ValueError, TypeError):
        return None
    if gb_amount > 2.0:
        return (
            f"Policy violation: data refueling is limited to 2 GB per request, "
            f"but {gb_amount} GB was requested."
        )
    return None


def rule_refuel_line_active(tool_name, tool_args, conversation, db):
    """Data refueling requires an active line (tools.py has the check commented out)."""
    if tool_name != "refuel_data":
        return None
    line_id = tool_args.get("line_id", "")
    line = _find_line(db, line_id)
    if not line:
        return None
    if line.status.value != "Active":
        return (
            f"Policy violation: cannot refuel data on line {line_id} — "
            f"status is '{line.status.value}', must be 'Active'."
        )
    return None


# ============================================================================
#  SEND PAYMENT REQUEST rules
#  Policy: "Check the bill status to make sure it is overdue."
#  Policy: "A user can only have one bill in the AWAITING PAYMENT status at a time."
# ============================================================================

def rule_payment_bill_must_be_overdue(tool_name, tool_args, conversation, db):
    """Payment request should only be sent for overdue bills."""
    if tool_name != "send_payment_request":
        return None
    bill_id = tool_args.get("bill_id", "")
    bill = _find_bill(db, bill_id)
    if not bill:
        return None
    if bill.status.value != "Overdue":
        return (
            f"Policy violation: payment request should only be sent for overdue "
            f"bills, but bill {bill_id} has status '{bill.status.value}'."
        )
    return None


def rule_payment_no_duplicate_awaiting(tool_name, tool_args, conversation, db):
    """A user can only have one bill in AWAITING PAYMENT status at a time."""
    if tool_name != "send_payment_request":
        return None
    customer_id = tool_args.get("customer_id", "")
    if not customer_id:
        return None
    if _has_awaiting_payment_bill(db, customer_id):
        return (
            f"Policy violation: customer {customer_id} already has a bill in "
            f"'Awaiting Payment' status. Only one bill can be awaiting payment "
            f"at a time."
        )
    return None


# ============================================================================
#  RESUME LINE rules
#  Policy: "You are not allowed to lift the suspension if the line's contract
#           end date is in the past."
#  Policy: "You are allowed to lift the suspension after the user has paid
#           all their overdue bills."
# ============================================================================

def rule_resume_contract_not_expired(tool_name, tool_args, conversation, db):
    """Cannot resume a line if the contract has expired."""
    if tool_name != "resume_line":
        return None
    line_id = tool_args.get("line_id", "")
    line = _find_line(db, line_id)
    if not line:
        return None
    if line.contract_end_date and line.contract_end_date < CURRENT_DATE:
        return (
            f"Policy violation: cannot resume line {line_id} — "
            f"contract expired on {line.contract_end_date} "
            f"(current date is {CURRENT_DATE})."
        )
    return None


def rule_resume_all_bills_paid(tool_name, tool_args, conversation, db):
    """Cannot resume a line until ALL overdue bills are paid."""
    if tool_name != "resume_line":
        return None
    customer_id = tool_args.get("customer_id", "")
    if _has_overdue_bills(db, customer_id):
        return (
            f"Policy violation: cannot resume line — customer {customer_id} "
            f"still has overdue bills. All overdue bills must be paid first."
        )
    return None


# ============================================================================
#  SUSPEND LINE rules
#  Policy: "A line can be suspended for the following reasons:
#           - The user has an overdue bill.
#           - The line's contract end date is in the past."
# ============================================================================

def rule_suspend_valid_reason(tool_name, tool_args, conversation, db):
    """Suspension reason must be for overdue bill or expired contract."""
    if tool_name != "suspend_line":
        return None
    from tau2.verifier.slm_helper import slm_extract
    reason = tool_args.get("reason", "")
    answer = slm_extract(
        "Is this suspension reason related to either an overdue bill / "
        "non-payment, or an expired contract? "
        "Answer 'yes' or 'no'.",
        [{"role": "system", "content": f"Suspension reason: {reason}"}],
    )
    if answer.strip().lower().startswith("no"):
        return (
            f"Policy violation: line suspension reason '{reason}' is not a valid "
            f"policy reason. Lines can only be suspended for overdue bills or "
            f"expired contracts."
        )
    return None


# ============================================================================
#  ENABLE ROAMING rules
#  Policy: "If a user is traveling outside their home network, you should
#           check if the line is roaming enabled. If it is not, you should
#           enable it at no cost for the user."
#  (No rule needed to block enable_roaming — it's always free and allowed.
#   But disable_roaming should not happen during tech support for a traveling user.)
# ============================================================================

def rule_disable_roaming_not_while_traveling(tool_name, tool_args, conversation, db):
    """Should not disable roaming if the user is traveling and needs data."""
    if tool_name != "disable_roaming":
        return None
    from tau2.verifier.slm_helper import slm_extract
    answer = slm_extract(
        "Is the user currently traveling outside their home network or abroad "
        "and experiencing data connectivity issues? "
        "Answer 'yes' or 'no'.",
        conversation,
    )
    if answer.strip().lower().startswith("yes"):
        return (
            "Policy violation: should not disable roaming when the user is "
            "traveling outside their home network. Roaming should be enabled "
            "at no cost for traveling users."
        )
    return None


# ============================================================================
#  TRANSFER TO HUMAN AGENT rules
#  Policy: "You should escalate to a human agent if and only if the request
#           cannot be handled within the scope of your actions."
#  Policy: "You should try your best to resolve the issue before escalating."
# ============================================================================

def _extract_tools_called(conversation: list[dict]) -> set[str]:
    """Extract all tool names already called from conversation history."""
    tools = set()
    for msg in conversation:
        # Solo mode: tool calls are in assistant messages
        if msg.get("role") == "assistant":
            for tc in (msg.get("tool_calls") or []):
                name = tc.get("name", tc.get("function", {}).get("name", ""))
                if name:
                    tools.add(name)
    return tools


def _infer_issue_type(conversation: list[dict], **kwargs) -> str | None:
    """Infer the issue type from the user's initial ticket/instructions."""
    # Use user_instructions (ticket) if available — most reliable source.
    verifier = kwargs.get("verifier")
    user_instr = getattr(verifier, "_user_instructions", None) if verifier else None
    if user_instr:
        text = user_instr.lower()
    else:
        # Fallback: use first message (in solo mode this is the assistant's
        # initial thinking which quotes the ticket).
        text = ""
        for msg in conversation:
            if msg.get("content"):
                text = str(msg["content"]).lower()
                break

    # Check for MMS keywords first (MMS is a superset of data/service)
    if any(kw in text for kw in (
        "mms", "picture message", "send picture", "send photo",
        "multimedia message",
    )):
        return "mms"
    # Check for data issue keywords
    if any(kw in text for kw in (
        "mobile data", "data issue", "internet",
        "slow data", "no data", "data not working",
        "cannot connect", "browsing", "data plan",
        "data speed", "connectivity issue",
    )):
        return "data"
    # Check for service keywords
    if any(kw in text for kw in (
        "no service", "no signal", "no network", "suspended",
        "can't make calls", "no connection", "service issue",
        "cannot call", "line suspended", "phone service",
    )):
        return "service"
    return None


# Required troubleshooting tools per issue type.
# We require the DIAGNOSTIC checks (not the fix tools), since the agent
# must at least check each category before deciding it's not relevant.
# If a diagnostic reveals a problem, the agent should fix it.
_REQUIRED_TOOLS: dict[str, dict[str, str]] = {
    "data": {
        "check_data_restriction_status": (
            "Check if Data Saver mode is on — if so, toggle it off "
            "with toggle_data_saver_mode"
        ),
        "check_network_mode_preference": (
            "Check the network mode preference — if it's wrong, fix it "
            "with set_network_mode_preference"
        ),
        "get_data_usage": (
            "Check if user's data usage has exceeded their limit — "
            "if so, refuel with refuel_data"
        ),
    },
    "mms": {
        "check_app_permissions": (
            "Check messaging app permissions — if sms or storage is "
            "missing, grant it with grant_app_permission('messaging', ...)"
        ),
        "check_apn_settings": (
            "Check APN/MMSC settings — if MMSC URL is missing, reset "
            "with reset_apn_settings then reboot_device"
        ),
        "check_wifi_calling_status": (
            "Check if Wi-Fi Calling is on — if so, disable it with "
            "toggle_wifi_calling (it can interfere with MMS)"
        ),
        "check_network_mode_preference": (
            "Check network mode — MMS requires at least 3G, fix with "
            "set_network_mode_preference if set to 2G only"
        ),
        "get_data_usage": (
            "Check if data limit is exceeded — MMS requires active "
            "data, refuel with refuel_data if needed"
        ),
    },
    "service": {
        "check_network_status": (
            "Check network status including airplane mode and data settings"
        ),
        "check_sim_status": (
            "Check SIM card status — reseat with reseat_sim_card if missing, "
            "or escalate if locked"
        ),
        "check_apn_settings": (
            "Check APN settings — reset with reset_apn_settings + "
            "reboot_device if incorrect"
        ),
    },
}


def rule_transfer_missing_tools(tool_name, tool_args, conversation, db, **kwargs):
    """Block transfer if the agent hasn't tried required troubleshooting tools."""
    if tool_name != "transfer_to_human_agents":
        return None

    tools_called = _extract_tools_called(conversation)
    issue_type = _infer_issue_type(conversation, **kwargs)

    if not issue_type:
        return None  # Can't determine issue type, allow transfer

    required = _REQUIRED_TOOLS.get(issue_type, {})
    missing = []
    for tool, hint in required.items():
        if tool not in tools_called:
            missing.append(f"  - {tool}: {hint}")

    if not missing:
        return None  # All required tools tried, transfer is valid

    missing_str = "\n".join(missing)
    return (
        f"Policy violation: you are escalating to a human agent but have not "
        f"tried the following troubleshooting steps:\n"
        f"{missing_str}\n"
        f"Please try these tools before escalating. Only transfer to a human "
        f"agent after exhausting all available troubleshooting options."
    )


# ============================================================================
#  SLM-based argument validation rules
# ============================================================================

def rule_arg_refuel_line(tool_name, tool_args, conversation, db):
    """Verify the refuel is being applied to the line the user discussed."""
    if tool_name != "refuel_data":
        return None
    from tau2.verifier.slm_helper import slm_extract
    line_id = tool_args.get("line_id", "")

    # Find the phone number for this line to check against conversation
    line = _find_line(db, line_id)
    if not line:
        return None

    answer = slm_extract(
        "What phone number or line does the user want to add data to? "
        "Reply with ONLY the phone number or line ID.",
        conversation,
    )
    raw_answer = answer.strip()
    mentioned = raw_answer.replace("-", "").replace(" ", "").lower()
    line_phone = line.phone_number.replace("-", "").replace(" ", "").lower()
    line_id_lower = line_id.lower()

    # Match either line_id or phone number anywhere in the SLM answer
    if (line_id_lower in mentioned or
            line_phone in mentioned or
            mentioned in line_phone or
            line_id_lower in raw_answer.lower()):
        return None

    # Fallback: check if the line_id appears in the conversation itself
    convo_text = " ".join(
        str(m.get("content", "")) for m in conversation
    ).lower()
    if line_id_lower in convo_text:
        return None

    return (
        f"Argument mismatch: refueling line {line_id} ({line.phone_number}) "
        f"but the user mentioned: {raw_answer}"
    )


def rule_arg_payment_bill(tool_name, tool_args, conversation, db):
    """Verify the payment request targets the bill the user discussed."""
    if tool_name != "send_payment_request":
        return None
    from tau2.verifier.slm_helper import slm_extract
    bill_id = tool_args.get("bill_id", "")
    answer = slm_extract(
        "What bill ID does the user want to pay? "
        "Reply with ONLY the bill ID (e.g. B1234321). "
        "Remove any hyphens or dashes from the ID.",
        conversation,
    )
    # Normalize both: strip hyphens, dashes, spaces for comparison
    mentioned = answer.strip().upper().replace(" ", "").replace("-", "")
    target = bill_id.upper().replace("-", "")
    if target and mentioned and target not in mentioned and mentioned not in target:
        # Fallback: check if the bill_id appears in the conversation itself
        convo_text = " ".join(
            str(m.get("content", "")) for m in conversation
        ).upper()
        if target in convo_text:
            return None
        return (
            f"Argument mismatch: sending payment for bill {bill_id} "
            f"but the user mentioned: {answer}"
        )
    return None


def rule_arg_resume_line(tool_name, tool_args, conversation, db):
    """Verify resume_line targets the correct line and customer."""
    if tool_name != "resume_line":
        return None
    from tau2.verifier.slm_helper import slm_extract
    line_id = tool_args.get("line_id", "")
    customer_id = tool_args.get("customer_id", "")

    line = _find_line(db, line_id)
    if not line:
        return None

    # Check the customer owns this line
    customer = _find_customer(db, customer_id)
    if customer and line_id not in customer.line_ids:
        return (
            f"Argument mismatch: line {line_id} does not belong to "
            f"customer {customer_id}."
        )

    answer = slm_extract(
        "What phone number or line does the user want to resume/unsuspend? "
        "Reply with ONLY the phone number or line ID.",
        conversation,
    )
    raw_answer = answer.strip()
    mentioned = raw_answer.replace("-", "").replace(" ", "").lower()
    line_phone = line.phone_number.replace("-", "").replace(" ", "").lower()
    line_id_lower = line_id.lower()

    if (line_id_lower in mentioned or
            line_phone in mentioned or
            mentioned in line_phone or
            line_id_lower in raw_answer.lower()):
        return None

    convo_text = " ".join(
        str(m.get("content", "")) for m in conversation
    ).lower()
    if line_id_lower in convo_text or line_phone in convo_text:
        return None

    return (
        f"Argument mismatch: resuming line {line_id} ({line.phone_number}) "
        f"but the user mentioned: {raw_answer}"
    )


def rule_arg_enable_roaming_line(tool_name, tool_args, conversation, db):
    """Verify enable_roaming targets the correct line."""
    if tool_name != "enable_roaming":
        return None
    from tau2.verifier.slm_helper import slm_extract
    line_id = tool_args.get("line_id", "")
    customer_id = tool_args.get("customer_id", "")

    line = _find_line(db, line_id)
    if not line:
        return None

    # Check the customer owns this line
    customer = _find_customer(db, customer_id)
    if customer and line_id not in customer.line_ids:
        return (
            f"Argument mismatch: line {line_id} does not belong to "
            f"customer {customer_id}."
        )

    answer = slm_extract(
        "What phone number or line is the user calling about? "
        "Reply with ONLY the phone number or line ID.",
        conversation,
    )
    raw_answer = answer.strip()
    mentioned = raw_answer.replace("-", "").replace(" ", "").lower()
    line_phone = line.phone_number.replace("-", "").replace(" ", "").lower()
    line_id_lower = line_id.lower()

    if (line_id_lower in mentioned or
            line_phone in mentioned or
            mentioned in line_phone or
            line_id_lower in raw_answer.lower()):
        return None

    convo_text = " ".join(
        str(m.get("content", "")) for m in conversation
    ).lower()
    if line_id_lower in convo_text or line_phone in convo_text:
        return None

    return (
        f"Argument mismatch: enabling roaming on line {line_id} ({line.phone_number}) "
        f"but the user mentioned: {raw_answer}"
    )


# ============================================================================
#  CUSTOMER LOOKUP rules
#  Policy: "For name lookup, date of birth is required for verification."
# ============================================================================

def rule_customer_lookup_name_requires_dob(tool_name, tool_args, conversation, db):
    """Name-based customer lookup must include date of birth."""
    if tool_name != "get_customer_by_name":
        return None
    dob = tool_args.get("dob", "")
    if not dob or not dob.strip():
        return (
            "Policy violation: looking up customer by name requires "
            "date of birth for verification purposes."
        )
    return None


# ============================================================================
#  Tech Support Workflow — Path 1: No Service
#  Policy (Step 1.4): "If the line is suspended ... follow the instructions
#          in the main policy for line suspension."
#  (resume_line rules already cover the main policy constraints.)
#
#  Policy (Step 1.2): "If SIM is LOCKED with PIN/PUK — Escalate to
#          technical support for assistance with SIM security."
#  (Transfer rule already prevents premature transfers; SIM lock is a valid
#   reason to escalate.)
# ============================================================================


# ============================================================================
#  Tech Support Workflow — Path 2: Data Issues
#  Policy (Step 2.1.4): "Check if user's data usage has exceeded their
#           data limit." If exceeded, refuel or change plan.
#  Policy: Refuel data max 2GB (already covered).
# ============================================================================

def rule_refuel_only_when_data_exceeded(tool_name, tool_args, conversation, db):
    """Data refueling should only be done when data usage exceeds the limit."""
    if tool_name != "refuel_data":
        return None
    line_id = tool_args.get("line_id", "")
    customer_id = tool_args.get("customer_id", "")

    line = _find_line(db, line_id)
    if not line:
        return None

    plan = _find_plan(db, line.plan_id)
    if not plan:
        return None

    total_available = plan.data_limit_gb + line.data_refueling_gb
    if line.data_used_gb <= total_available:
        # Data is not exceeded — refueling might still be requested by user
        # proactively, so only warn if usage is well under limit
        if line.data_used_gb < plan.data_limit_gb * 0.8:
            from tau2.verifier.slm_helper import slm_extract
            answer = slm_extract(
                "Did the user explicitly ask to add/refuel more data to their "
                "line, or is the agent doing it as part of troubleshooting a "
                "data connectivity issue? Answer 'user requested' or "
                "'troubleshooting'.",
                conversation,
            )
            if "troubleshooting" in answer.strip().lower():
                return (
                    f"Policy violation: data refueling line {line_id} but data "
                    f"usage ({line.data_used_gb} GB) is well below the limit "
                    f"({plan.data_limit_gb} GB). Data connectivity issues should "
                    f"be diagnosed through the troubleshooting workflow first."
                )
    return None


# ============================================================================
#  Rule registry & check_all
# ============================================================================

ALL_RULES = [
    # Refuel data
    rule_refuel_max_2gb,
    rule_refuel_line_active,
    rule_refuel_only_when_data_exceeded,
    rule_arg_refuel_line,
    # Payment
    rule_payment_bill_must_be_overdue,
    rule_payment_no_duplicate_awaiting,
    rule_arg_payment_bill,
    # Resume line
    rule_resume_contract_not_expired,
    rule_resume_all_bills_paid,
    rule_arg_resume_line,
    # Suspend line
    rule_suspend_valid_reason,
    # Roaming
    rule_disable_roaming_not_while_traveling,
    rule_arg_enable_roaming_line,
    # Customer lookup
    rule_customer_lookup_name_requires_dob,
    # Transfer
    rule_transfer_missing_tools,
]

CHEAP_RULES = [
    rule_refuel_max_2gb,
    rule_refuel_line_active,
    rule_payment_bill_must_be_overdue,
    rule_payment_no_duplicate_awaiting,
    rule_resume_contract_not_expired,
    rule_resume_all_bills_paid,
    rule_customer_lookup_name_requires_dob,
    rule_transfer_missing_tools,
]

SLM_RULES = [r for r in ALL_RULES if r not in CHEAP_RULES]

# Argument-accuracy rules: these only need the ticket/instructions context,
# not the full conversation. Passing a shorter context to the SLM yields
# more reliable extraction and is cheaper.
ARG_RULES = {
    rule_arg_refuel_line,
    rule_arg_payment_bill,
    rule_arg_resume_line,
    rule_arg_enable_roaming_line,
}

# Rules that need access to the verifier / kwargs (e.g., user_instructions).
_KWARGS_RULES = {
    rule_transfer_missing_tools,
}


def check_all(
    tool_name: str,
    tool_args: dict,
    conversation: list[dict],
    db,
    cheap_only: bool = False,
    **kwargs,
) -> str | None:
    """Run all applicable telecom policy rules against a tool call."""
    rules = CHEAP_RULES if cheap_only else ALL_RULES

    # Extract user instructions (ticket) from verifier for arg-accuracy rules.
    # This is much shorter than the full conversation and contains all the
    # key identifiers (phone number, customer name, etc.) upfront.
    verifier = kwargs.get("verifier")
    user_instructions = (
        getattr(verifier, "_user_instructions", None) if verifier else None
    )
    if user_instructions:
        short_context = [{"role": "system", "content": user_instructions}]
    else:
        short_context = conversation

    for rule_fn in rules:
        try:
            # Arg-accuracy rules use the short ticket context;
            # policy-constraint rules use the full conversation.
            ctx = short_context if rule_fn in ARG_RULES else conversation
            if rule_fn in _KWARGS_RULES:
                result = rule_fn(tool_name, tool_args, ctx, db, **kwargs)
            else:
                result = rule_fn(tool_name, tool_args, ctx, db)
            if result is not None:
                logger.info("Rule %s violated: %s", rule_fn.__name__, result)
                return result
        except Exception as e:
            logger.warning("Rule %s raised exception: %s", rule_fn.__name__, e)
            continue

    return None
