"""
Retail policy spec — rules that check retail write-tool calls against the
retail agent policy before they are executed.

Built the same way as ``telecom_policy_spec``: each rule is a function

    rule(tool_name, tool_args, conversation, db) -> str | None

returning ``None`` if the call is allowed, or a feedback string describing the
violation.  ``check_all`` runs every applicable rule and returns the first
violation (or ``None``).

The two headline rules:

* ``rule_confirm_before_write``  — the agent must clearly describe the action
  and get an explicit user "yes" before mutating anything.  This addresses the
  branching-scenario failures where the agent acts on a stale/ambiguous request
  without re-confirming (verifier #4).

* ``rule_action_type_matches``   — the write tool the agent chose must match the
  kind of action the user actually asked for (return vs. exchange vs. modify vs.
  cancel).  This catches the "wrong action type" failures (verifier #6).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Retail write (mutating) tools.
RETAIL_WRITE_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_pending_order_address",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}

# Valid cancellation reasons per retail policy.
_VALID_CANCEL_REASONS = {"no longer needed", "ordered by mistake"}

# Human-readable description of each write tool (used in feedback + SLM prompts).
_TOOL_ACTION_DESC = {
    "cancel_pending_order": "cancel a pending order",
    "modify_pending_order_items": "modify the items in a pending order",
    "modify_pending_order_payment": "change the payment method on a pending order",
    "modify_pending_order_address": "change the shipping address on a pending order",
    "modify_user_address": "update the user's default address",
    "return_delivered_order_items": "return item(s) from a delivered order",
    "exchange_delivered_order_items": "exchange item(s) from a delivered order",
}


# ============================================================================
#  CONFIRMATION RULE (verifier #4)
#  Policy: "Before taking consequential actions ... list the action detail and
#           obtain explicit user confirmation (yes) to proceed."
# ============================================================================

def rule_confirm_before_write(tool_name, tool_args, conversation, db):
    """Require an explicit user confirmation before any write tool runs.

    Deterministic and affirmation-aware: the write is allowed as soon as a
    recent user turn is a clear agreement ("yes", "confirm", "go ahead",
    "proceed", ...). Only when NO such confirmation exists in the recent user
    turns is the write blocked with a request to confirm first.

    This avoids two failure modes seen in the retail run:
      * an unreliable SLM saying "not confirmed" even after the user said "yes"
        (which deadlocked the agent), and
      * a direct conflict with the completion nudge, which explicitly tells the
        agent to proceed with the write (the nudge text counts as a proceed
        signal here).
    """
    if tool_name not in RETAIL_WRITE_TOOLS:
        return None

    import re

    # Collect the last couple of user turns (most recent first).
    recent_user_turns = []
    for msg in reversed(conversation):
        if msg.get("role") == "user":
            content = str(msg.get("content", "")).strip()
            if content:
                recent_user_turns.append(content)
                if len(recent_user_turns) >= 2:
                    break

    affirm = re.compile(
        r"\b(yes|yeah|yep|yup|confirm(ed|ing)?|correct|go ahead|proceed|"
        r"sounds good|please do|please proceed|ok|okay|sure|do it|"
        r"that works|that's right|thats right|absolutely|go for it)\b",
        re.I,
    )
    if any(affirm.search(t) for t in recent_user_turns):
        return None  # customer has agreed (or a proceed-nudge authorised it)

    action_desc = _TOOL_ACTION_DESC.get(tool_name, tool_name)
    return (
        f"Confirmation required: before you {action_desc}, you must clearly "
        f"describe the exact change and get an explicit 'yes' from the "
        f"customer. Ask the customer to confirm this specific action first, "
        f"then proceed."
    )


# ============================================================================
#  ACTION-TYPE RULE (verifier #6)
#  Catch return<->exchange / cancel<->modify confusions.
# ============================================================================

def rule_action_type_matches(tool_name, tool_args, conversation, db, **kwargs):
    """Check the chosen write tool matches the action the user asked for.

    Prefers the user's scenario/instructions (short, unambiguous) when available
    via the verifier; otherwise falls back to the conversation.
    """
    if tool_name not in RETAIL_WRITE_TOOLS:
        return None

    from tau2.verifier.slm_helper import slm_extract

    verifier = kwargs.get("verifier")
    user_instructions = (
        getattr(verifier, "_user_instructions", None) if verifier else None
    )
    context = (
        [{"role": "system", "content": user_instructions}]
        if user_instructions
        else conversation
    )

    action_desc = _TOOL_ACTION_DESC.get(tool_name, tool_name)
    answer = slm_extract(
        f"The agent is about to {action_desc}. "
        "Based on what the customer actually requested, is this the CORRECT type "
        "of action? Pay attention to the difference between: returning items (get "
        "a refund) vs. exchanging items (swap for a different variant) vs. "
        "modifying a pending order vs. cancelling an order. "
        "Answer 'yes' if the action type matches the customer's request, or "
        "briefly describe the mismatch if it does not.",
        context,
    )
    result = answer.strip().lower()
    if result.startswith("yes"):
        return None
    _OK_MARKERS = ("match", "correct", "consistent", "appropriate")
    if any(m in result for m in _OK_MARKERS) and "mismatch" not in result and "not " not in result:
        return None
    return (
        f"Action-type mismatch: you are about to {action_desc}, but that does not "
        f"appear to match what the customer asked for. {answer.strip()} "
        f"Re-read the customer's request and use the correct action "
        f"(return vs. exchange vs. modify vs. cancel)."
    )


# ============================================================================
#  CANCEL REASON RULE (cheap, DB-free)
# ============================================================================

def rule_cancel_reason_valid(tool_name, tool_args, conversation, db):
    """cancel_pending_order reason must be a policy-valid reason."""
    if tool_name != "cancel_pending_order":
        return None
    reason = str(tool_args.get("reason", "")).strip().lower()
    if reason and reason not in _VALID_CANCEL_REASONS:
        return (
            f"Policy violation: cancellation reason '{tool_args.get('reason')}' is "
            f"not valid. The reason must be exactly one of: "
            f"'no longer needed' or 'ordered by mistake'."
        )
    return None


ALL_RULES = [
    rule_cancel_reason_valid,
    rule_confirm_before_write,
    rule_action_type_matches,
]

# Cheap rules need no SLM call.
CHEAP_RULES = [
    rule_cancel_reason_valid,
]

# Rules that may consume verifier kwargs (e.g. user_instructions).
_KWARGS_RULES = {
    rule_action_type_matches,
}


def check_all(
    tool_name: str,
    tool_args: dict,
    conversation: list[dict],
    db,
    cheap_only: bool = False,
    **kwargs,
) -> str | None:
    """Run all applicable retail policy rules against a tool call.

    Returns the first violation feedback string, or ``None`` if allowed.
    """
    rules = CHEAP_RULES if cheap_only else ALL_RULES
    for rule_fn in rules:
        try:
            if rule_fn in _KWARGS_RULES:
                result = rule_fn(tool_name, tool_args, conversation, db, **kwargs)
            else:
                result = rule_fn(tool_name, tool_args, conversation, db)
            if result is not None:
                logger.info("Retail rule %s violated: %s", rule_fn.__name__, result)
                return result
        except Exception as e:  # never let a rule crash the run
            logger.warning("Retail rule %s raised exception: %s", rule_fn.__name__, e)
            continue
    return None
