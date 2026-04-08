"""
Telecom Policy Spec — verifiable rules extracted from main_policy.md.

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


# ============================================================================
#  REFUEL DATA rules
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


# ============================================================================
#  RESUME LINE rules
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
#  SLM-based argument validation rules
# ============================================================================

def rule_arg_refuel_line(tool_name, tool_args, conversation, db):
    """Verify the refuel is being applied to the line the user discussed."""
    if tool_name != "refuel_data":
        return None
    from tau2.verifier.slm_helper import slm_extract
    line_id = tool_args.get("line_id", "")
    customer_id = tool_args.get("customer_id", "")

    # Find the phone number for this line to check against conversation
    line = _find_line(db, line_id)
    if not line:
        return None

    answer = slm_extract(
        "What phone number or line does the user want to add data to? "
        "Reply with ONLY the phone number or line ID.",
        conversation,
    )
    mentioned = answer.strip().replace("-", "").replace(" ", "")
    line_phone = line.phone_number.replace("-", "").replace(" ", "")

    # Match either line_id or phone number
    if (line_id.lower() not in mentioned.lower() and
            line_phone not in mentioned and
            mentioned not in line_phone):
        return (
            f"Argument mismatch: refueling line {line_id} ({line.phone_number}) "
            f"but the user mentioned: {answer}"
        )
    return None


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
        return (
            f"Argument mismatch: sending payment for bill {bill_id} "
            f"but the user mentioned: {answer}"
        )
    return None


# ============================================================================
#  TRANSFER rule (SLM)
# ============================================================================

def rule_transfer_only_when_needed(tool_name, tool_args, conversation, db):
    """Transfer to human only when request cannot be handled by agent."""
    if tool_name != "transfer_to_human_agents":
        return None
    from tau2.verifier.slm_helper import slm_extract
    answer = slm_extract(
        "Is the user's request something the agent cannot handle with the "
        "available telecom tools (billing, line suspend/resume, data refuel, "
        "roaming, plan lookup)? "
        "Answer 'yes' if the request is outside what the tools can do, "
        "'no' if the agent could still handle it.",
        conversation,
    )
    if answer.strip().lower().startswith("no"):
        return (
            "Policy violation: transferring to human agent but the user's "
            "request can likely be handled with the available tools. "
            "Try to resolve the request first."
        )
    return None


# ============================================================================
#  Rule registry & check_all
# ============================================================================

ALL_RULES = [
    # Refuel data
    rule_refuel_max_2gb,
    rule_refuel_line_active,
    rule_arg_refuel_line,
    # Payment
    rule_payment_bill_must_be_overdue,
    rule_arg_payment_bill,
    # Resume line
    rule_resume_contract_not_expired,
    rule_resume_all_bills_paid,
    # Suspend line
    rule_suspend_valid_reason,
    # Transfer
    rule_transfer_only_when_needed,
]

CHEAP_RULES = [
    rule_refuel_max_2gb,
    rule_refuel_line_active,
    rule_payment_bill_must_be_overdue,
    rule_resume_contract_not_expired,
    rule_resume_all_bills_paid,
]

SLM_RULES = [r for r in ALL_RULES if r not in CHEAP_RULES]


def check_all(
    tool_name: str,
    tool_args: dict,
    conversation: list[dict],
    db,
    cheap_only: bool = False,
) -> str | None:
    """Run all applicable telecom policy rules against a tool call."""
    rules = CHEAP_RULES if cheap_only else ALL_RULES

    for rule_fn in rules:
        try:
            result = rule_fn(tool_name, tool_args, conversation, db)
            if result is not None:
                logger.info("Rule %s violated: %s", rule_fn.__name__, result)
                return result
        except Exception as e:
            logger.warning("Rule %s raised exception: %s", rule_fn.__name__, e)
            continue

    return None
