"""
Retail Policy Spec — verifiable rules extracted from policy.md.

Each rule is a function that takes:
  - tool_name: str           (the tool being called)
  - tool_args: dict          (the arguments passed to the tool)
  - conversation: list[dict] (recent message history for SLM extraction)
  - db: RetailDB             (current database state for lookups)

And returns:
  - None            if the call is ALLOWED (rule passes or doesn't apply)
  - str             a feedback message explaining the violation
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
#  Helpers
# ============================================================================

def _get_order(db, order_id: str):
    """Safely get an order from the DB."""
    return db.orders.get(order_id)


def _get_user(db, user_id: str):
    """Safely get a user from the DB."""
    return db.users.get(user_id)


def _get_product_for_item(db, item_id: str):
    """Find the product that contains a given item (variant) ID."""
    for product in db.products.values():
        if item_id in product.variants:
            return product
    return None


# ============================================================================
#  CANCEL PENDING ORDER rules
# ============================================================================

def rule_cancel_order_status(tool_name, tool_args, conversation, db):
    """Can only cancel orders with status 'pending'."""
    if tool_name != "cancel_pending_order":
        return None
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None
    if order.status != "pending":
        return (
            f"Policy violation: cannot cancel order {order_id} — "
            f"status is '{order.status}', must be 'pending'."
        )
    return None


def rule_cancel_reason(tool_name, tool_args, conversation, db):
    """Cancel reason must be 'no longer needed' or 'ordered by mistake'."""
    if tool_name != "cancel_pending_order":
        return None
    reason = tool_args.get("reason", "")
    valid_reasons = {"no longer needed", "ordered by mistake"}
    if reason not in valid_reasons:
        return (
            f"Policy violation: cancel reason '{reason}' is invalid. "
            f"Must be one of: {valid_reasons}."
        )
    return None


# ============================================================================
#  MODIFY PENDING ORDER — items
# ============================================================================

def rule_modify_items_order_status(tool_name, tool_args, conversation, db):
    """Item modifications require exactly 'pending' status (not 'pending (item modified)')."""
    if tool_name != "modify_pending_order_items":
        return None
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None
    if order.status != "pending":
        return (
            f"Policy violation: cannot modify items on order {order_id} — "
            f"status is '{order.status}'. Items can only be modified once "
            f"and the order must be in 'pending' status."
        )
    return None


def rule_modify_items_same_product(tool_name, tool_args, conversation, db):
    """New items must be from the same product as the items they replace."""
    if tool_name != "modify_pending_order_items":
        return None
    old_item_ids = tool_args.get("item_ids", [])
    new_item_ids = tool_args.get("new_item_ids", [])

    for old_id, new_id in zip(old_item_ids, new_item_ids):
        old_product = _get_product_for_item(db, old_id)
        new_product = _get_product_for_item(db, new_id)
        if old_product and new_product and old_product.product_id != new_product.product_id:
            return (
                f"Policy violation: item {new_id} is from product "
                f"'{new_product.product_id}' but the original item {old_id} "
                f"is from product '{old_product.product_id}'. "
                f"Can only exchange for the same product type."
            )
    return None


def rule_modify_items_count_match(tool_name, tool_args, conversation, db):
    """Number of old items and new items must match."""
    if tool_name != "modify_pending_order_items":
        return None
    old_ids = tool_args.get("item_ids", [])
    new_ids = tool_args.get("new_item_ids", [])
    if len(old_ids) != len(new_ids):
        return (
            f"Policy violation: must replace items 1-to-1. "
            f"Got {len(old_ids)} old items but {len(new_ids)} new items."
        )
    return None


def rule_modify_items_gift_card_balance(tool_name, tool_args, conversation, db):
    """If paying with gift card, balance must cover the price difference."""
    if tool_name != "modify_pending_order_items":
        return None
    payment_method_id = tool_args.get("payment_method_id", "")
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None

    # Find the user who owns this order
    user = _get_user(db, order.user_id)
    if not user:
        return None

    pm = user.payment_methods.get(payment_method_id)
    if not pm:
        return None

    source = getattr(pm, "source", "")
    if source != "gift_card":
        return None

    # Calculate price difference
    old_ids = tool_args.get("item_ids", [])
    new_ids = tool_args.get("new_item_ids", [])

    old_total = 0.0
    new_total = 0.0
    for oid in old_ids:
        for item in order.items:
            if item.item_id == oid:
                old_total += item.price
                break

    for nid in new_ids:
        product = _get_product_for_item(db, nid)
        if product and nid in product.variants:
            variant = product.variants[nid]
            new_total += variant.price

    diff = new_total - old_total
    if diff > 0:
        balance = getattr(pm, "balance", 0.0)
        if balance < diff:
            return (
                f"Policy violation: gift card '{payment_method_id}' has balance "
                f"${balance:.2f} but the price difference is ${diff:.2f}."
            )
    return None


# ============================================================================
#  MODIFY PENDING ORDER — payment
# ============================================================================

def rule_modify_payment_order_status(tool_name, tool_args, conversation, db):
    """Payment modification requires a pending order."""
    if tool_name != "modify_pending_order_payment":
        return None
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None
    if "pending" not in order.status:
        return (
            f"Policy violation: cannot modify payment on order {order_id} — "
            f"status is '{order.status}', must contain 'pending'."
        )
    return None


def rule_modify_payment_different(tool_name, tool_args, conversation, db):
    """New payment method must differ from current."""
    if tool_name != "modify_pending_order_payment":
        return None
    order_id = tool_args.get("order_id", "")
    payment_method_id = tool_args.get("payment_method_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None

    # Current payment method from payment history
    if order.payment_history:
        current_id = order.payment_history[-1].payment_method_id
        if current_id == payment_method_id:
            return (
                f"Policy violation: new payment method '{payment_method_id}' "
                f"is the same as the current payment method."
            )
    return None


def rule_modify_payment_gift_card_balance(tool_name, tool_args, conversation, db):
    """If paying with gift card, balance must cover order total."""
    if tool_name != "modify_pending_order_payment":
        return None
    order_id = tool_args.get("order_id", "")
    payment_method_id = tool_args.get("payment_method_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None

    user = _get_user(db, order.user_id)
    if not user:
        return None

    pm = user.payment_methods.get(payment_method_id)
    if not pm:
        return None

    source = getattr(pm, "source", "")
    if source != "gift_card":
        return None

    order_total = sum(item.price for item in order.items)
    balance = getattr(pm, "balance", 0.0)
    if balance < order_total:
        return (
            f"Policy violation: gift card '{payment_method_id}' has balance "
            f"${balance:.2f} but order total is ${order_total:.2f}."
        )
    return None


# ============================================================================
#  MODIFY PENDING ORDER — address
# ============================================================================

def rule_modify_address_order_status(tool_name, tool_args, conversation, db):
    """Address modification requires a pending order."""
    if tool_name != "modify_pending_order_address":
        return None
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None
    if "pending" not in order.status:
        return (
            f"Policy violation: cannot modify address on order {order_id} — "
            f"status is '{order.status}', must contain 'pending'."
        )
    return None


# ============================================================================
#  RETURN DELIVERED ORDER rules
# ============================================================================

def rule_return_order_status(tool_name, tool_args, conversation, db):
    """Returns require 'delivered' status."""
    if tool_name != "return_delivered_order_items":
        return None
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None
    if order.status != "delivered":
        return (
            f"Policy violation: cannot return items from order {order_id} — "
            f"status is '{order.status}', must be 'delivered'."
        )
    return None


def rule_return_payment_method(tool_name, tool_args, conversation, db):
    """Return refund must go to original payment method or a gift card."""
    if tool_name != "return_delivered_order_items":
        return None
    order_id = tool_args.get("order_id", "")
    payment_method_id = tool_args.get("payment_method_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None

    user = _get_user(db, order.user_id)
    if not user:
        return None

    # Check if it's the original payment method
    original_ids = {p.payment_method_id for p in order.payment_history}
    if payment_method_id in original_ids:
        return None

    # Or a gift card
    pm = user.payment_methods.get(payment_method_id)
    if pm and getattr(pm, "source", "") == "gift_card":
        return None

    return (
        f"Policy violation: return refund must go to the original payment "
        f"method or a gift card, but '{payment_method_id}' is neither."
    )


# ============================================================================
#  EXCHANGE DELIVERED ORDER rules
# ============================================================================

def rule_exchange_order_status(tool_name, tool_args, conversation, db):
    """Exchanges require 'delivered' status."""
    if tool_name != "exchange_delivered_order_items":
        return None
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None
    if order.status != "delivered":
        return (
            f"Policy violation: cannot exchange items from order {order_id} — "
            f"status is '{order.status}', must be 'delivered'."
        )
    return None


def rule_exchange_same_product(tool_name, tool_args, conversation, db):
    """Exchange items must be from the same product type."""
    if tool_name != "exchange_delivered_order_items":
        return None
    old_item_ids = tool_args.get("item_ids", [])
    new_item_ids = tool_args.get("new_item_ids", [])

    for old_id, new_id in zip(old_item_ids, new_item_ids):
        old_product = _get_product_for_item(db, old_id)
        new_product = _get_product_for_item(db, new_id)
        if old_product and new_product and old_product.product_id != new_product.product_id:
            return (
                f"Policy violation: exchange item {new_id} is from product "
                f"'{new_product.product_id}' but the original item {old_id} "
                f"is from product '{old_product.product_id}'. "
                f"Can only exchange for the same product type."
            )
    return None


def rule_exchange_count_match(tool_name, tool_args, conversation, db):
    """Number of old items and new items must match."""
    if tool_name != "exchange_delivered_order_items":
        return None
    old_ids = tool_args.get("item_ids", [])
    new_ids = tool_args.get("new_item_ids", [])
    if len(old_ids) != len(new_ids):
        return (
            f"Policy violation: must exchange items 1-to-1. "
            f"Got {len(old_ids)} old items but {len(new_ids)} new items."
        )
    return None


def rule_exchange_gift_card_balance(tool_name, tool_args, conversation, db):
    """If paying with gift card for exchange price diff, balance must cover it."""
    if tool_name != "exchange_delivered_order_items":
        return None
    payment_method_id = tool_args.get("payment_method_id", "")
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None

    user = _get_user(db, order.user_id)
    if not user:
        return None

    pm = user.payment_methods.get(payment_method_id)
    if not pm:
        return None

    source = getattr(pm, "source", "")
    if source != "gift_card":
        return None

    old_ids = tool_args.get("item_ids", [])
    new_ids = tool_args.get("new_item_ids", [])

    old_total = 0.0
    new_total = 0.0
    for oid in old_ids:
        for item in order.items:
            if item.item_id == oid:
                old_total += item.price
                break

    for nid in new_ids:
        product = _get_product_for_item(db, nid)
        if product and nid in product.variants:
            variant = product.variants[nid]
            new_total += variant.price

    diff = new_total - old_total
    if diff > 0:
        balance = getattr(pm, "balance", 0.0)
        if balance < diff:
            return (
                f"Policy violation: gift card '{payment_method_id}' has balance "
                f"${balance:.2f} but the exchange price difference is ${diff:.2f}."
            )
    return None


# ============================================================================
#  ORDER OWNERSHIP rule (cheap DB check)
# ============================================================================

def rule_order_belongs_to_user(tool_name, tool_args, conversation, db):
    """Write operations on an order must target an order owned by the user
    who was authenticated (or at least the user_id on the order)."""
    write_tools_with_order = {
        "cancel_pending_order",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "modify_pending_order_address",
        "return_delivered_order_items",
        "exchange_delivered_order_items",
    }
    if tool_name not in write_tools_with_order:
        return None
    # This check is about consistency — the order's user_id must match one
    # of the users that has been looked up in this conversation.
    # Since we can't easily track "authenticated user" state, we just
    # verify the order exists and belongs to a valid user.
    order_id = tool_args.get("order_id", "")
    order = _get_order(db, order_id)
    if not order:
        return None
    user = _get_user(db, order.user_id)
    if not user:
        return (
            f"Policy violation: order {order_id} belongs to user "
            f"'{order.user_id}' which does not exist in the database."
        )
    return None


# ============================================================================
#  SLM-based argument validation rules
# ============================================================================

def rule_arg_cancel_order(tool_name, tool_args, conversation, db):
    """Verify the order being cancelled matches what the user discussed."""
    if tool_name != "cancel_pending_order":
        return None
    from tau2.verifier.slm_helper import slm_extract
    order_id = tool_args.get("order_id", "")
    answer = slm_extract(
        f"What order ID does the user want to cancel? "
        f"Reply with ONLY the order ID (e.g. #W1234567).",
        conversation,
    )
    mentioned = answer.strip().upper().replace(" ", "")
    target = order_id.upper()
    if target and mentioned and target not in mentioned and mentioned not in target:
        return (
            f"Argument mismatch: trying to cancel order {order_id} "
            f"but the user asked to cancel: {answer}"
        )
    return None


def rule_arg_return_order(tool_name, tool_args, conversation, db):
    """Verify the order being returned matches what the user discussed."""
    if tool_name != "return_delivered_order_items":
        return None
    from tau2.verifier.slm_helper import slm_extract
    order_id = tool_args.get("order_id", "")
    answer = slm_extract(
        f"What order ID does the user want to return items from? "
        f"Reply with ONLY the order ID (e.g. #W1234567).",
        conversation,
    )
    mentioned = answer.strip().upper().replace(" ", "")
    target = order_id.upper()
    if target and mentioned and target not in mentioned and mentioned not in target:
        return (
            f"Argument mismatch: trying to return from order {order_id} "
            f"but the user mentioned: {answer}"
        )
    return None


def rule_arg_exchange_order(tool_name, tool_args, conversation, db):
    """Verify the order being exchanged matches what the user discussed."""
    if tool_name != "exchange_delivered_order_items":
        return None
    from tau2.verifier.slm_helper import slm_extract
    order_id = tool_args.get("order_id", "")
    answer = slm_extract(
        f"What order ID does the user want to exchange items from? "
        f"Reply with ONLY the order ID (e.g. #W1234567).",
        conversation,
    )
    mentioned = answer.strip().upper().replace(" ", "")
    target = order_id.upper()
    if target and mentioned and target not in mentioned and mentioned not in target:
        return (
            f"Argument mismatch: trying to exchange from order {order_id} "
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
        "available tools (cancel/modify/return/exchange pending or delivered orders)? "
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
    # Cancel
    rule_cancel_order_status,
    rule_cancel_reason,
    rule_arg_cancel_order,
    # Modify items
    rule_modify_items_order_status,
    rule_modify_items_same_product,
    rule_modify_items_count_match,
    rule_modify_items_gift_card_balance,
    # Modify payment
    rule_modify_payment_order_status,
    rule_modify_payment_different,
    rule_modify_payment_gift_card_balance,
    # Modify address
    rule_modify_address_order_status,
    # Return
    rule_return_order_status,
    rule_return_payment_method,
    rule_arg_return_order,
    # Exchange
    rule_exchange_order_status,
    rule_exchange_same_product,
    rule_exchange_count_match,
    rule_exchange_gift_card_balance,
    rule_arg_exchange_order,
    # Order ownership
    rule_order_belongs_to_user,
    # Transfer
    rule_transfer_only_when_needed,
]

CHEAP_RULES = [
    rule_cancel_order_status,
    rule_cancel_reason,
    rule_modify_items_order_status,
    rule_modify_items_same_product,
    rule_modify_items_count_match,
    rule_modify_items_gift_card_balance,
    rule_modify_payment_order_status,
    rule_modify_payment_different,
    rule_modify_payment_gift_card_balance,
    rule_modify_address_order_status,
    rule_return_order_status,
    rule_return_payment_method,
    rule_exchange_order_status,
    rule_exchange_same_product,
    rule_exchange_count_match,
    rule_exchange_gift_card_balance,
    rule_order_belongs_to_user,
]

SLM_RULES = [r for r in ALL_RULES if r not in CHEAP_RULES]


def check_all(
    tool_name: str,
    tool_args: dict,
    conversation: list[dict],
    db,
    cheap_only: bool = False,
) -> str | None:
    """Run all applicable retail policy rules against a tool call."""
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
