"""
Retail **policy** spec — deterministic (and one SLM-assisted) verifiers that
encode the rules in ``data/tau2/domains/retail/policy.md``.

These are *policy* verifiers only: each one is a literal encoding of a sentence
in the retail policy. They are checked **before** a write tool executes and, if
violated, return a feedback string that the orchestrator turns into a
``[VERIFIER]`` block so the agent can correct itself. This module contains the
retail *policy* verifiers only.

Rule signature::

    rule(tool_name, tool_args, conversation, db, verifier=None) -> str | None

returns ``None`` if the call is allowed, or a feedback string describing the
policy violation. ``check_all`` runs every applicable rule and returns the first
violation (or ``None``).

Policy clauses encoded here (from policy.md)
--------------------------------------------
* "authenticate the user identity by locating their user id via email, or via
  name + zip code ... even when the user already provides the user id."
      -> rule_authenticate_before_write
* "You can only help one user per conversation ... must deny any requests for
  tasks related to any other user."
      -> rule_single_user_per_conversation
* "Before taking any action that updates the database ... you must list the
  action details and obtain explicit user confirmation (yes) to proceed."
      -> rule_confirm_before_write            (SLM-assisted)
* Cancel reason must be 'no longer needed' or 'ordered by mistake'.
      -> rule_cancel_reason_valid
* Cancel/modify only on 'pending'; return/exchange only on 'delivered'.
      -> rule_status_precondition
* "Exchange or modify order tools can only be called once per order."
      -> rule_once_per_order
* Modify/exchange items: 1-to-1, same product type, different available variant.
      -> rule_item_variant_same_product
* Modify/exchange with a gift card must have enough balance for the price diff.
      -> rule_item_giftcard_balance
* Modify payment: a single payment method different from the original.
      -> rule_payment_method_different
* Modify payment to a gift card must have enough balance for the total.
      -> rule_payment_giftcard_balance
* Return refund must go to the original payment method or an existing gift card.
      -> rule_return_refund_destination
"""

from __future__ import annotations

import json as _json
import logging
import os
import re

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool sets (from policy.md)
# ---------------------------------------------------------------------------

RETAIL_WRITE_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_pending_order_address",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}

# Tools that act on a *pending* order.
_PENDING_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_pending_order_address",
}

# Tools that act on a *delivered* order.
_DELIVERED_TOOLS = {
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}

# "Exchange or modify order tools can only be called once per order."
_ONCE_PER_ORDER_TOOLS = {
    "modify_pending_order_items",
    "exchange_delivered_order_items",
}

# Read/lookup tools that establish authentication (locate the user id).
_AUTH_TOOLS = {
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
}

# Valid cancellation reasons per policy.
_VALID_CANCEL_REASONS = {"no longer needed", "ordered by mistake"}

# Human-readable description of each write tool (used in feedback strings).
_TOOL_ACTION_DESC = {
    "cancel_pending_order": "cancel a pending order",
    "modify_pending_order_items": "modify the items in a pending order",
    "modify_pending_order_payment": "change the payment method on a pending order",
    "modify_pending_order_address": "change the shipping address on a pending order",
    "modify_user_address": "update the user's default address",
    "return_delivered_order_items": "return item(s) from a delivered order",
    "exchange_delivered_order_items": "exchange item(s) from a delivered order",
}


# ---------------------------------------------------------------------------
# Conversation helpers (deterministic — no SLM)
# ---------------------------------------------------------------------------

def _iter_prior_tool_calls(conversation):
    """Yield ``(name, args_dict, result_content)`` for every prior assistant
    tool call in ``conversation`` paired with its following tool-result message.

    ``result_content`` is ``None`` when no result message follows (call not
    executed / blocked). Arguments are best-effort JSON-decoded.
    """
    msgs = conversation or []
    for i, m in enumerate(msgs):
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", tc)
            name = fn.get("name")
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = _json.loads(args)
                except Exception:
                    args = {}
            result = None
            for m2 in msgs[i + 1 : i + 4]:
                if m2.get("role") == "tool":
                    result = str(m2.get("content", ""))
                    break
            yield name, (args or {}), result


def _call_succeeded(result_content) -> bool:
    """A prior tool call counts as executed only if it produced a real result
    that is not a verifier block or an error string."""
    if not result_content:
        return False
    head = result_content.lstrip()[:80]
    if head.startswith("[VERIFIER]") or head.startswith("[HINT]"):
        return False
    if re.match(r"(?i)^error\b", head):
        return False
    return True


_AFFIRM_RE = re.compile(
    r"\b(yes|yeah|yep|yup|confirm(ed|ing)?|correct|go ahead|proceed|"
    r"sounds good|please do|please proceed|ok|okay|sure|do it|"
    r"that works|that's right|thats right|absolutely|go for it)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_order(db, order_id):
    try:
        return db.orders.get(order_id)
    except Exception:
        return None


def _get_user(db, user_id):
    try:
        return db.users.get(user_id)
    except Exception:
        return None


def _original_payment_method_id(order):
    """Return the payment_method_id of the order's original *payment* (not a
    refund), or ``None`` if it cannot be determined."""
    try:
        for p in order.payment_history:
            if getattr(p, "transaction_type", None) == "payment":
                return p.payment_method_id
        # fallback: first entry
        if order.payment_history:
            return order.payment_history[0].payment_method_id
    except Exception:
        pass
    return None


def _original_payment_amount(order):
    """Total of the order's original payment transaction(s)."""
    try:
        payments = [
            p.amount for p in order.payment_history
            if getattr(p, "transaction_type", None) == "payment"
        ]
        if payments:
            return round(sum(payments), 2)
    except Exception:
        pass
    return None


def _find_product_of_item(db, item_id):
    try:
        for product in db.products.values():
            if item_id in product.variants:
                return product
    except Exception:
        return None
    return None


def _get_payment_method(db, user, payment_method_id):
    try:
        return user.payment_methods.get(payment_method_id)
    except Exception:
        return None


def _is_gift_card(pm) -> bool:
    return getattr(pm, "source", "") == "gift_card"


# ============================================================================
#  AUTHENTICATION
#  policy: "authenticate the user identity by locating their user id via email,
#  or via name + zip code. This has to be done even when the user already
#  provides the user id."
# ============================================================================

def rule_authenticate_before_write(tool_name, tool_args, conversation, db, verifier=None):
    """Block any write before the user has been authenticated via a user-id
    lookup (``find_user_id_by_email`` or ``find_user_id_by_name_zip``)."""
    if tool_name not in RETAIL_WRITE_TOOLS:
        return None

    block_msg = (
        "Authentication required: you must first authenticate the user by "
        "locating their user id via email or via name + zip code "
        "(find_user_id_by_email or find_user_id_by_name_zip) before taking any "
        "action that changes the database. This is required even if the user "
        "already provided their user id."
    )

    # Authoritative runtime path: tools the orchestrator recorded as executed.
    if verifier is not None:
        called = getattr(verifier, "_called_all_tools", None) or []
        return None if (_AUTH_TOOLS & set(called)) else block_msg

    # Fallback (no verifier — unit tests): parse the conversation.
    for name, _args, result in _iter_prior_tool_calls(conversation):
        if name in _AUTH_TOOLS and _call_succeeded(result):
            return None
    return block_msg


# ============================================================================
#  ONE USER PER CONVERSATION
#  policy: "You can only help one user per conversation ... must deny any
#  requests for tasks related to any other user."
# ============================================================================

def _authenticated_user_ids(conversation):
    """Collect user ids that were positively resolved via a successful
    ``find_user_id_*`` call in this conversation."""
    ids = set()
    for name, _args, result in _iter_prior_tool_calls(conversation):
        if name in _AUTH_TOOLS and _call_succeeded(result):
            uid = (result or "").strip().strip('"')
            # find_user_id_* returns a bare user id string.
            if uid and re.fullmatch(r"[A-Za-z0-9_\-]+", uid):
                ids.add(uid)
    return ids


def rule_single_user_per_conversation(tool_name, tool_args, conversation, db, verifier=None):
    """Deny a write whose target order/user belongs to a user other than the
    one authenticated in this conversation.

    Conservative: only blocks when we can positively identify the authenticated
    user id(s) *and* the target clearly belongs to a different user.
    """
    if tool_name not in RETAIL_WRITE_TOOLS:
        return None

    auth_ids = _authenticated_user_ids(conversation)
    if not auth_ids:
        return None  # cannot determine — let auth rule handle the missing case

    # Resolve the target user id for this write.
    target_user = None
    if tool_name == "modify_user_address":
        target_user = tool_args.get("user_id")
    else:
        order = _get_order(db, tool_args.get("order_id"))
        if order is not None:
            target_user = getattr(order, "user_id", None)

    if target_user and target_user not in auth_ids:
        return (
            f"Policy violation: this action targets user '{target_user}', but the "
            f"authenticated user for this conversation is "
            f"{sorted(auth_ids)}. You can only help one user per conversation and "
            f"must deny requests related to any other user."
        )
    return None


# ============================================================================
#  CONFIRMATION  (SLM-assisted)
#  policy: "Before taking any action that updates the database (cancel, modify,
#  return, exchange), you must list the action details and obtain explicit user
#  confirmation (yes) to proceed."
# ============================================================================

def _slm_user_confirmed(conversation) -> bool | None:
    """Ask the SLM (port 8001) whether the customer explicitly confirmed the
    agent's most recently proposed database action.

    Returns True/False, or ``None`` if the SLM is unavailable / inconclusive.
    """
    try:
        from tau2.verifier.slm_helper import slm_extract
    except Exception:
        return None
    try:
        answer = slm_extract(
            "The agent proposed an action that changes the customer's order or "
            "profile (cancel, modify, return, or exchange). In the customer's "
            "MOST RECENT message, did the customer explicitly agree/confirm "
            "(e.g. say 'yes', 'confirm', 'go ahead') to proceed with that "
            "specific action? Answer only 'yes' or 'no'.",
            conversation,
            max_tokens=8,
        )
    except Exception:
        return None
    a = (answer or "").strip().lower()
    if a.startswith("yes"):
        return True
    if a.startswith("no"):
        return False
    return None


def rule_confirm_before_write(tool_name, tool_args, conversation, db, verifier=None):
    """Require an explicit recent user confirmation before any write tool runs.

    Fast path: a clear affirmation in the last couple of user turns (regex).
    If none is found, consult the SLM to decide (a "small extraction"). Only
    block when neither the regex nor the SLM finds a confirmation.
    """
    if tool_name not in RETAIL_WRITE_TOOLS:
        return None

    recent_user_turns = []
    for msg in reversed(conversation or []):
        if msg.get("role") == "user":
            content = str(msg.get("content", "")).strip()
            if content:
                recent_user_turns.append(content)
                if len(recent_user_turns) >= 2:
                    break

    if any(_AFFIRM_RE.search(t) for t in recent_user_turns):
        return None

    # No obvious affirmation — ask the SLM before blocking.
    slm = _slm_user_confirmed(conversation)
    if slm is True:
        return None

    action_desc = _TOOL_ACTION_DESC.get(tool_name, tool_name)
    return (
        f"Confirmation required: before you {action_desc}, you must clearly list "
        f"the exact details of the change and obtain an explicit 'yes' from the "
        f"customer. Describe this specific action and ask the customer to confirm "
        f"first, then proceed."
    )


# ============================================================================
#  CANCEL REASON
#  policy: reason must be 'no longer needed' or 'ordered by mistake'.
# ============================================================================

def rule_cancel_reason_valid(tool_name, tool_args, conversation, db, verifier=None):
    if tool_name != "cancel_pending_order":
        return None
    reason = str(tool_args.get("reason", "")).strip().lower()
    if reason and reason not in _VALID_CANCEL_REASONS:
        return (
            f"Policy violation: cancellation reason '{tool_args.get('reason')}' is "
            f"not valid. The reason must be exactly one of: 'no longer needed' or "
            f"'ordered by mistake'. Ask the customer which of these applies."
        )
    return None


# ============================================================================
#  STATUS PRE-CONDITION
#  policy: cancel/modify only if 'pending'; return/exchange only if 'delivered';
#  "you should check its status before taking the action."
# ============================================================================

def rule_status_precondition(tool_name, tool_args, conversation, db, verifier=None):
    if tool_name not in _PENDING_TOOLS and tool_name not in _DELIVERED_TOOLS:
        return None
    order = _get_order(db, tool_args.get("order_id"))
    if order is None:
        return None  # unknown order — let the tool surface the error
    order_id = tool_args.get("order_id")
    status = str(getattr(order, "status", ""))

    if tool_name in _PENDING_TOOLS and status != "pending":
        if status.startswith("pending"):
            return (
                f"Policy violation: order {order_id} has status '{status}'. Its "
                f"items were already modified, so it can no longer be modified or "
                f"cancelled."
            )
        alt = ""
        if status == "delivered":
            alt = (
                " If the customer wants to return or exchange a delivered order, "
                "use return_delivered_order_items or exchange_delivered_order_items."
            )
        return (
            f"Policy violation: order {order_id} has status '{status}', but "
            f"'{tool_name}' can only be used on a 'pending' order. Check the order "
            f"status before acting.{alt}"
        )

    if tool_name in _DELIVERED_TOOLS and status != "delivered":
        alt = ""
        if status.startswith("pending"):
            alt = (
                " If the customer wants to cancel or modify a pending order, use "
                "cancel_pending_order or the modify_pending_order_* tools."
            )
        return (
            f"Policy violation: order {order_id} has status '{status}', but "
            f"'{tool_name}' can only be used on a 'delivered' order. Check the "
            f"order status before acting.{alt}"
        )
    return None


# ============================================================================
#  ONCE PER ORDER
#  policy: "Exchange or modify order tools can only be called once per order."
# ============================================================================

def rule_once_per_order(tool_name, tool_args, conversation, db, verifier=None):
    if tool_name not in _ONCE_PER_ORDER_TOOLS:
        return None
    order_id = tool_args.get("order_id")
    if not order_id:
        return None
    for name, args, result in _iter_prior_tool_calls(conversation):
        if (
            name in _ONCE_PER_ORDER_TOOLS
            and args.get("order_id") == order_id
            and _call_succeeded(result)
        ):
            return (
                f"Policy violation: a modify/exchange action has already been "
                f"performed on order {order_id}. Exchange or modify order tools can "
                f"only be called ONCE per order — collect all items into a single "
                f"call. This order can no longer be modified or exchanged."
            )
    return None


# ============================================================================
#  ITEM VARIANT
#  policy: "each item can be modified/exchanged to an available new item of the
#  same product but of different product option. There cannot be any change of
#  product types."
# ============================================================================

def rule_item_variant_same_product(tool_name, tool_args, conversation, db, verifier=None):
    if tool_name not in ("modify_pending_order_items", "exchange_delivered_order_items"):
        return None
    old_ids = tool_args.get("item_ids") or []
    new_ids = tool_args.get("new_item_ids") or []

    if len(old_ids) != len(new_ids):
        return (
            f"Policy violation: you provided {len(old_ids)} item(s) to change but "
            f"{len(new_ids)} replacement(s). Each item must map 1-to-1 to exactly "
            f"one new item. Provide exactly {len(old_ids)} new item id(s)."
        )

    for old_id, new_id in zip(old_ids, new_ids):
        old_prod = _find_product_of_item(db, old_id)
        new_prod = _find_product_of_item(db, new_id)
        if old_prod is None or new_prod is None:
            continue  # unknown id — let the tool surface the error
        if old_prod.product_id != new_prod.product_id:
            avail = [
                vid for vid, v in old_prod.variants.items()
                if getattr(v, "available", True) and vid != old_id
            ]
            hint = f" Available variants of '{old_prod.name}': {avail[:8]}." if avail else ""
            return (
                f"Policy violation: item {old_id} is a '{old_prod.name}' but the "
                f"replacement {new_id} is a '{new_prod.name}'. You can only change "
                f"an item to a different variant of the SAME product type.{hint}"
            )
        variant = new_prod.variants.get(new_id)
        if variant is not None and getattr(variant, "available", True) is False:
            return (
                f"Policy violation: the chosen replacement item {new_id} "
                f"('{new_prod.name}') is not available. Pick an available variant."
            )
        if new_id == old_id:
            return (
                f"Policy violation: replacement item {new_id} is identical to the "
                f"original. Choose a different (available) variant of the same product."
            )
    return None


# ============================================================================
#  ITEM PRICE-DIFFERENCE GIFT CARD BALANCE
#  policy (modify/exchange items): "If the user provides a gift card, it must
#  have enough balance to cover the price difference."
# ============================================================================

def rule_item_giftcard_balance(tool_name, tool_args, conversation, db, verifier=None):
    if tool_name not in ("modify_pending_order_items", "exchange_delivered_order_items"):
        return None
    pid = tool_args.get("payment_method_id")
    order = _get_order(db, tool_args.get("order_id"))
    if order is None or not pid:
        return None
    user = _get_user(db, getattr(order, "user_id", None))
    if user is None:
        return None
    pm = _get_payment_method(db, user, pid)
    if pm is None or not _is_gift_card(pm):
        return None  # not a gift card — no balance constraint here

    old_ids = tool_args.get("item_ids") or []
    new_ids = tool_args.get("new_item_ids") or []
    if len(old_ids) != len(new_ids):
        return None  # 1-to-1 rule handles this

    diff = 0.0
    try:
        order_items = {it.item_id: it for it in order.items}
        for old_id, new_id in zip(old_ids, new_ids):
            old_item = order_items.get(old_id)
            new_prod = _find_product_of_item(db, new_id)
            if old_item is None or new_prod is None:
                return None  # cannot price reliably — let the tool decide
            new_variant = new_prod.variants.get(new_id)
            if new_variant is None:
                return None
            diff += float(new_variant.price) - float(old_item.price)
        diff = round(diff, 2)
    except Exception:
        return None

    balance = float(getattr(pm, "balance", 0) or 0)
    if diff > 0 and balance < diff:
        return (
            f"Policy violation: gift card {pid} has a balance of ${balance:.2f}, "
            f"which is not enough to cover the price difference of ${diff:.2f}. "
            f"Ask the customer for a payment method that can cover it."
        )
    return None


# ============================================================================
#  MODIFY PAYMENT — DIFFERENT METHOD
#  policy: "The user can only choose a single payment method different from the
#  original payment method."
# ============================================================================

def rule_payment_method_different(tool_name, tool_args, conversation, db, verifier=None):
    if tool_name != "modify_pending_order_payment":
        return None
    order = _get_order(db, tool_args.get("order_id"))
    new_pid = tool_args.get("payment_method_id")
    if order is None or not new_pid:
        return None
    original = _original_payment_method_id(order)
    if original and new_pid == original:
        return (
            f"Policy violation: the new payment method must be DIFFERENT from the "
            f"order's original payment method ('{original}'). Ask the customer for "
            f"a different payment method."
        )
    return None


# ============================================================================
#  MODIFY PAYMENT — GIFT CARD BALANCE
#  policy: "If the user wants the modify the payment method to gift card, it
#  must have enough balance to cover the total amount."
# ============================================================================

def rule_payment_giftcard_balance(tool_name, tool_args, conversation, db, verifier=None):
    if tool_name != "modify_pending_order_payment":
        return None
    pid = tool_args.get("payment_method_id")
    order = _get_order(db, tool_args.get("order_id"))
    if order is None or not pid:
        return None
    user = _get_user(db, getattr(order, "user_id", None))
    if user is None:
        return None
    pm = _get_payment_method(db, user, pid)
    if pm is None or not _is_gift_card(pm):
        return None
    total = _original_payment_amount(order)
    if total is None:
        return None
    balance = float(getattr(pm, "balance", 0) or 0)
    if balance < total:
        return (
            f"Policy violation: gift card {pid} has a balance of ${balance:.2f}, "
            f"which is not enough to cover the order total of ${total:.2f}. A gift "
            f"card can only be used as the new payment method if it covers the full "
            f"amount."
        )
    return None


# ============================================================================
#  RETURN — REFUND DESTINATION
#  policy: "The refund must either go to the original payment method, or an
#  existing gift card."
# ============================================================================

def rule_return_refund_destination(tool_name, tool_args, conversation, db, verifier=None):
    if tool_name != "return_delivered_order_items":
        return None
    pid = tool_args.get("payment_method_id")
    order = _get_order(db, tool_args.get("order_id"))
    if order is None or not pid:
        return None
    original = _original_payment_method_id(order)
    if pid == original:
        return None
    user = _get_user(db, getattr(order, "user_id", None))
    if user is None:
        return None
    pm = _get_payment_method(db, user, pid)
    if pm is not None and _is_gift_card(pm):
        return None
    gift_cards = [
        gid for gid, m in getattr(user, "payment_methods", {}).items()
        if _is_gift_card(m)
    ]
    hint = f" Valid options: original payment method '{original}'"
    if gift_cards:
        hint += f" or a gift card {gift_cards}."
    else:
        hint += "."
    return (
        f"Policy violation: refund destination '{pid}' is not allowed. The refund "
        f"must go to the order's original payment method or to an existing gift "
        f"card.{hint}"
    )


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

# Rules that need no DB access (pure args / conversation / verifier state).
CHEAP_RULES = [
    rule_authenticate_before_write,
    rule_confirm_before_write,
    rule_cancel_reason_valid,
    rule_once_per_order,
]

# All policy verifiers (cheap + DB-backed). Only rule_confirm_before_write may
# call the SLM (port 8001); everything else is deterministic.
ALL_RULES = [
    rule_authenticate_before_write,
    rule_single_user_per_conversation,
    rule_confirm_before_write,
    rule_cancel_reason_valid,
    rule_status_precondition,
    rule_once_per_order,
    rule_item_variant_same_product,
    rule_item_giftcard_balance,
    rule_payment_method_different,
    rule_payment_giftcard_balance,
    rule_return_refund_destination,
]


def check_all(
    tool_name: str,
    tool_args: dict,
    conversation: list[dict],
    db,
    cheap_only: bool = False,
    **kwargs,
) -> str | None:
    """Run all applicable retail **policy** verifiers against a tool call.

    Returns the first violation feedback string, or ``None`` if allowed.
    ``verifier`` (from ``**kwargs``) gives rules access to reliable runtime
    state such as successfully-executed tools.
    """
    verifier = kwargs.get("verifier")
    rules = CHEAP_RULES if cheap_only else ALL_RULES
    for rule_fn in rules:
        try:
            result = rule_fn(tool_name, tool_args, conversation, db, verifier=verifier)
        except Exception as e:  # never let a rule crash the run
            logger.warning("Retail policy rule %s raised: %s", rule_fn.__name__, e)
            continue
        if result is not None:
            logger.info("Retail policy rule %s violated: %s", rule_fn.__name__, result)
            return result
    return None
