"""Opt-in, stateful retail verifiers derived from policy-run trace failures.

These checks are intentionally separate from ``retail_policy_spec`` because
they are empirical safeguards, not direct encodings of policy.md. They run only
when ``TAU2_RETAIL_TRACE_VERIFIERS=1``.

The policy-only run showed two recurring, related failures:

* selecting the wrong write action (return vs exchange, cancel vs modify,
  order address vs default user address); and
* selecting the right write tool with details that do not match the confirmed
  request (wrong order, incomplete item set, replacement, payment method, or
  address).

Each simulation has a JSON state file containing the SLM's current extraction
of active requests, revisions, details, and confirmation status. The state is
updated after every user turn, so a later decision supersedes stale intent and
requires fresh confirmation. Proposed writes and task completion are checked
against that latest state.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import uuid

logger = logging.getLogger(__name__)


RETAIL_ACTION_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_pending_order_address",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}

_VALID_STATUSES = {
    "gathering_details",
    "awaiting_confirmation",
    "confirmed",
    "completed",
    "cancelled",
}

_AFFIRM_RE = re.compile(
    r"\b(yes|yeah|yep|confirm(?:ed)?|go ahead|proceed|please do|okay|ok|sure|do it)\b",
    re.IGNORECASE,
)

_DECISION_CHANGE_RE = re.compile(
    r"\b(changed? my mind|instead|rather|only|do not|don't|no longer|actually)\b",
    re.IGNORECASE,
)


def _empty_state(simulation_id: str, task_id: str) -> dict:
    return {
        "version": 1,
        "simulation_id": simulation_id,
        "task_id": task_id,
        "revision": 0,
        "latest_decision_summary": "",
        "requests": [],
        "completed_writes": [],
    }


def configure_state(verifier, simulation_id: str, task_id: str) -> None:
    """Assign a unique, persisted state file to this simulation."""
    root = Path(
        os.getenv(
            "TAU2_RETAIL_TRACE_STATE_DIR",
            str(Path(tempfile.gettempdir()) / "tau2-retail-trace-state"),
        )
    )
    root.mkdir(parents=True, exist_ok=True)
    safe_task = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(task_id))[:80] or "task"
    safe_sim = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(simulation_id))[:80]
    if not safe_sim:
        safe_sim = uuid.uuid4().hex
    verifier._retail_trace_state_path = root / f"{safe_task}__{safe_sim}.json"
    verifier._retail_trace_state = _empty_state(str(simulation_id), str(task_id))
    _write_state(verifier)


def _state(verifier) -> dict | None:
    if verifier is None:
        return None
    state = getattr(verifier, "_retail_trace_state", None)
    if isinstance(state, dict):
        return state
    path = getattr(verifier, "_retail_trace_state_path", None)
    if path:
        try:
            loaded = json.loads(Path(path).read_text())
            if isinstance(loaded, dict):
                verifier._retail_trace_state = loaded
                return loaded
        except Exception as exc:
            logger.warning("Could not load retail trace state %s: %s", path, exc)
    return None


def _write_state(verifier) -> None:
    state = _state(verifier)
    path = getattr(verifier, "_retail_trace_state_path", None)
    if state is None or path is None:
        return
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _ground_action(action: str, user_text: str, db, details: dict) -> str | None:
    """Ground a newly extracted action in explicit customer language and DB state."""
    text = user_text.lower()
    order_id = str(details.get("order_id") or details.get("order_number") or "")
    if order_id and not order_id.startswith("#"):
        order_id = "#" + order_id
    order = None
    try:
        order = db.orders.get(order_id) if db is not None and order_id else None
    except Exception:
        pass
    order_status = str(getattr(order, "status", ""))

    if re.search(r"\b(return|refund)\b", text):
        return "return_delivered_order_items" if action in {
            "return_delivered_order_items",
            "exchange_delivered_order_items",
        } else None
    if re.search(r"\b(exchange|swap)\b", text):
        if action not in {
            "exchange_delivered_order_items",
            "modify_pending_order_items",
        }:
            return None
        return (
            "modify_pending_order_items"
            if order_status == "pending"
            else "exchange_delivered_order_items"
        )
    if re.search(r"\bcancel(?:led|ing|lation)?\b", text):
        return "cancel_pending_order" if action == "cancel_pending_order" else None
    if re.search(r"\b(default|profile|user)\s+address\b", text):
        return "modify_user_address" if action in {
            "modify_user_address",
            "modify_pending_order_address",
        } else None
    if re.search(r"\b(order|shipping|delivery)\s+address\b", text):
        return "modify_pending_order_address" if action in {
            "modify_user_address",
            "modify_pending_order_address",
        } else None
    if re.search(r"\b(payment method|pay with|use (?:my )?(?:card|paypal|gift card))\b", text):
        return (
            "modify_pending_order_payment"
            if action == "modify_pending_order_payment"
            else None
        )
    if re.search(
        r"\b(modify|change|replace)\b.{0,40}\b(item|product|variant|option)\b",
        text,
    ):
        if action not in {
            "modify_pending_order_items",
            "exchange_delivered_order_items",
        }:
            return None
        return (
            "exchange_delivered_order_items"
            if order_status == "delivered"
            else "modify_pending_order_items"
        )

    return None


def _validate_state(candidate, previous: dict, user_text: str, db) -> dict | None:
    if not isinstance(candidate, dict) or not isinstance(candidate.get("requests"), list):
        return None
    normalized = _empty_state(previous["simulation_id"], previous["task_id"])
    normalized["revision"] = int(previous.get("revision", 0)) + 1
    normalized["latest_decision_summary"] = str(
        candidate.get("latest_decision_summary", "")
    )[:1000]
    normalized["completed_writes"] = list(previous.get("completed_writes", []))
    seen = set()
    seen_signatures = set()
    previous_by_id = {
        str(request.get("id")): request for request in previous.get("requests", [])
    }
    previous_actions = {
        request.get("action") for request in previous.get("requests", [])
    }
    decision_changed = bool(_DECISION_CHANGE_RE.search(user_text))
    for index, request in enumerate(candidate["requests"]):
        if not isinstance(request, dict):
            continue
        action = str(request.get("action", ""))
        status = str(request.get("status", ""))
        if status not in _VALID_STATUSES:
            continue
        request_id = str(request.get("id") or f"request-{index + 1}")[:100]
        details = request.get("details")
        details = details if isinstance(details, dict) else {}
        prior = previous_by_id.get(request_id)
        if (
            prior is not None
            and prior.get("action") == action
            and (not decision_changed or status in {"completed", "cancelled"})
        ):
            grounded_action = action
        elif action in previous_actions and not decision_changed:
            # Preserve an unaffected request when the SLM changes its id during
            # authentication, detail gathering, or a terse confirmation turn.
            grounded_action = action
        else:
            grounded_action = _ground_action(action, user_text, db, details)
        if grounded_action not in RETAIL_ACTION_TOOLS:
            logger.warning(
                "Dropping ungrounded retail trace request %s (%s)",
                request_id,
                action,
            )
            continue
        action = grounded_action
        signature = (action, json.dumps(details, sort_keys=True))
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        if request_id in seen:
            request_id = f"{request_id}-{index + 1}"
        seen.add(request_id)
        normalized["requests"].append(
            {
                "id": request_id,
                "action": action,
                "status": status,
                "details": details if isinstance(details, dict) else {},
                "summary": str(request.get("summary", ""))[:1000],
                "confirmation_basis": str(request.get("confirmation_basis", ""))[:500],
                "supersedes": str(request.get("supersedes", ""))[:100],
            }
        )
    if not decision_changed:
        normalized_actions = {r["action"] for r in normalized["requests"]}
        for prior in previous.get("requests", []):
            if (
                prior.get("status") in {
                    "gathering_details", "awaiting_confirmation", "confirmed"
                }
                and prior.get("action") not in normalized_actions
            ):
                normalized["requests"].append(copy.deepcopy(prior))
    if not decision_changed and normalized["completed_writes"]:
        completed_by_action = {}
        for completed in normalized["completed_writes"]:
            completed_by_action.setdefault(completed.get("tool_name"), []).append(completed)
        for request in normalized["requests"]:
            request_text = json.dumps(request, sort_keys=True)
            same_action = completed_by_action.get(request.get("action"), [])
            for completed in same_action:
                if completed.get("tool_name") != request.get("action"):
                    continue
                completed_args = completed.get("tool_args") or {}
                identifiers = [
                    str(completed_args.get(key))
                    for key in ("order_id", "user_id")
                    if completed_args.get(key)
                ]
                if not identifiers or any(value in request_text for value in identifiers):
                    request["status"] = "completed"
                    request["completion"] = "successful_tool_call"
            if len(same_action) == 1 and request.get("status") != "completed":
                request["status"] = "completed"
                request["completion"] = "successful_tool_call_same_action"
    return normalized


def _latest_assistant_text(conversation: list[dict]) -> str:
    for message in reversed(conversation[:-1]):
        if message.get("role") == "assistant" and message.get("content"):
            return str(message["content"])
    return ""


def _apply_explicit_confirmation(
    state: dict,
    conversation: list[dict],
    user_text: str,
) -> None:
    """Deterministically confirm a summarized proposal after an explicit yes.

    The SLM occasionally leaves the request awaiting confirmation even when the
    immediately preceding agent turn summarized the action and asked to proceed.
    A same-turn decision change always wins and prevents this override.
    """
    if _DECISION_CHANGE_RE.search(user_text) or not _AFFIRM_RE.search(user_text):
        return
    assistant_text = _latest_assistant_text(conversation).lower()
    if not re.search(r"\b(confirm|proceed|go ahead|shall i|would you like me)\b", assistant_text):
        return
    pending = _active_requests(
        state, {"gathering_details", "awaiting_confirmation"}
    )
    if not pending:
        return
    for request in pending:
        request["status"] = "confirmed"
        request["confirmation_basis"] = user_text[:500]


def _latest_confirmation_pair(conversation: list[dict]) -> tuple[str, str]:
    """Return latest confirmation and agent summaries in its decision epoch."""
    latest_user = ""
    for index in range(len(conversation) - 1, -1, -1):
        message = conversation[index]
        content = str(message.get("content", "")).strip()
        if message.get("role") == "user" and content:
            latest_user = content
            assistant_texts = []
            for prior in reversed(conversation[:index]):
                prior_content = str(prior.get("content", "")).strip()
                if (
                    prior.get("role") == "assistant"
                    and prior_content
                    and not prior_content.startswith("[Tool call:")
                ):
                    assistant_texts.append(prior_content)
                elif prior.get("role") == "user" and prior_content:
                    # Pure yes/proceed turns do not change the proposal. Stop at
                    # the latest substantive customer selection or revision.
                    if not _is_pure_affirmation(prior_content):
                        break
            return latest_user, "\n".join(reversed(assistant_texts))
            break
    return latest_user, ""


def _is_pure_affirmation(text: str) -> bool:
    if not _AFFIRM_RE.search(text) or _DECISION_CHANGE_RE.search(text):
        return False
    if re.match(
        r"^\s*(yes\b|i\s+confirm\b|confirmed\b|please\s+proceed\b)",
        text,
        re.IGNORECASE,
    ):
        return True
    # IDs, addresses, or concrete action nouns indicate a new/changed decision,
    # not a bare confirmation of the existing proposal.
    if re.search(r"#W\d+|\b\d{7,}\b", text, re.IGNORECASE):
        return False
    if re.search(
        r"\b(return|exchange|cancel|modify|address|item|water bottle|desk lamp|"
        r"keyboard|thermostat|t-?shirt)\b",
        text,
        re.IGNORECASE,
    ) and len(text.split()) > 10:
        return False
    return True


def _required_confirmation_values(tool_name: str, tool_args: dict) -> list[str]:
    keys = {
        "cancel_pending_order": ("order_id", "reason"),
        "modify_pending_order_items": (
            "order_id", "item_ids", "new_item_ids",
        ),
        "modify_pending_order_payment": ("order_id", "payment_method_id"),
        "modify_pending_order_address": (
            "order_id", "address1", "city", "state", "zip",
        ),
        "modify_user_address": ("user_id", "address1", "city", "state", "zip"),
        "return_delivered_order_items": (
            "order_id", "item_ids",
        ),
        "exchange_delivered_order_items": (
            "order_id", "item_ids", "new_item_ids",
        ),
    }.get(tool_name, ())
    values = []
    for key in keys:
        value = tool_args.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item)
        elif value not in (None, ""):
            values.append(str(value))
    return values


def _has_exact_confirmation(
    tool_name: str,
    tool_args: dict,
    conversation: list[dict],
) -> bool:
    """Require exact agent-presented details followed by an unchanged yes."""
    user_text, assistant_text = _latest_confirmation_pair(conversation)
    if (
        not user_text
        or not assistant_text
        or not _AFFIRM_RE.search(user_text)
        or _DECISION_CHANGE_RE.search(user_text)
    ):
        return False
    if not re.search(
        r"\b(confirm|proceed|go ahead|shall i|would you like me|reply with)\b",
        assistant_text,
        re.IGNORECASE,
    ):
        return False
    normalized_agent = assistant_text.lower()
    values = _required_confirmation_values(tool_name, tool_args)
    return bool(values) and all(value.lower() in normalized_agent for value in values)


def _proposal_facts(db, tool_name: str, tool_args: dict) -> dict:
    """Resolve proposed IDs and related orders into compact authoritative facts."""
    facts = {"tool": tool_name, "arguments": tool_args}
    order_id = tool_args.get("order_id")
    order = None
    try:
        order = db.orders.get(order_id) if order_id else None
    except Exception:
        pass
    if order is not None:
        facts["target_order"] = {
            "order_id": order_id,
            "status": str(getattr(order, "status", "")),
            "user_id": getattr(order, "user_id", None),
            "items": [
                {
                    "item_id": item.item_id,
                    "product_id": item.product_id,
                    "name": item.name,
                    "options": item.options,
                }
                for item in getattr(order, "items", [])
            ],
        }
        try:
            related = []
            for related_order in db.orders.values():
                if related_order.user_id != order.user_id:
                    continue
                related.append(
                    {
                        "order_id": related_order.order_id,
                        "status": str(related_order.status),
                        "items": [
                            {
                                "item_id": item.item_id,
                                "name": item.name,
                                "options": item.options,
                            }
                            for item in related_order.items
                        ],
                    }
                )
            facts["authenticated_users_orders"] = related
        except Exception:
            pass
    variants = []
    for item_id in tool_args.get("new_item_ids") or []:
        try:
            for product in db.products.values():
                variant = product.variants.get(item_id)
                if variant is not None:
                    variants.append(
                        {
                            "item_id": item_id,
                            "product_id": product.product_id,
                            "product_name": product.name,
                            "options": variant.options,
                            "available": variant.available,
                        }
                    )
                    break
        except Exception:
            break
    if variants:
        facts["proposed_new_variants"] = variants
    return facts


def _direct_write_decision_check(
    tool_name: str,
    tool_args: dict,
    conversation: list[dict],
    db,
) -> str | None:
    """Compare the write directly to the latest decision, independent of state."""
    from tau2.verifier.slm_helper import slm_extract_json

    question = (
        "Audit the proposed retail write against ONLY the customer-visible "
        "conversation and authoritative DB facts below. The customer's latest "
        "decision, correction, narrowing, option preference, and change of mind "
        "supersede earlier requests. Check action type, all requested items, target "
        "order/profile, replacement attributes and fallback preferences, payment, "
        "reason, and address. If the customer asked for ALL matching pending items, "
        "ensure the proposal covers all matching items in the DB facts. Never use "
        "hidden task instructions. Return JSON only: "
        "{\"verdict\":\"match|mismatch|unclear\",\"reason\":\"short concrete reason\"}. "
        "Use mismatch only for a clear contradiction or omission; use unclear if "
        "the conversation does not determine the answer.\nAuthoritative facts:\n"
        + json.dumps(_proposal_facts(db, tool_name, tool_args), sort_keys=True)
    )
    try:
        answer = slm_extract_json(question, conversation, max_tokens=220)
    except Exception as exc:
        logger.warning("Direct retail decision check failed: %s", exc)
        return None
    if not isinstance(answer, dict) or answer.get("verdict") != "mismatch":
        return None
    return str(answer.get("reason") or "proposed write conflicts with latest decision")


def _user_text(conversation: list[dict]) -> str:
    return "\n".join(
        str(message.get("content", ""))
        for message in conversation
        if message.get("role") == "user"
        and not str(message.get("content", "")).startswith("###STOP###")
    ).lower()


def _deterministic_target_item_check(
    tool_name: str,
    tool_args: dict,
    conversation: list[dict],
    db,
) -> str | None:
    """Check explicit descriptors that select which owned item may be changed."""
    if tool_name not in {
        "modify_pending_order_items", "exchange_delivered_order_items"
    }:
        return None
    order = None
    try:
        order = db.orders.get(tool_args.get("order_id"))
    except Exception:
        pass
    if order is None:
        return None
    text = _user_text(conversation)
    order_items = {item.item_id: item for item in order.items}
    size_words = {
        "small": "s", "medium": "m", "large": "l",
        "extra large": "xl", "xxl": "xxl",
    }
    for item_id in tool_args.get("item_ids") or []:
        item = order_items.get(item_id)
        if item is None:
            continue
        product_name = item.name.lower()
        if product_name == "t-shirt":
            normalized_text = text.replace("tshirt", "t-shirt")
            for word, expected_size in size_words.items():
                if re.search(
                    rf"\b{re.escape(word)}\s+t-?shirts?\b",
                    normalized_text,
                ) and str(item.options.get("size", "")).lower() != expected_size:
                    return (
                        f"customer selected {word} t-shirts, but item {item_id} "
                        f"has size '{item.options.get('size')}'"
                    )
            if (
                re.search(r"\b(?:same\s+)?v-?neck\b", normalized_text)
                and str(item.options.get("style", "")).lower() != "v-neck"
            ):
                return (
                    f"customer selected a v-neck t-shirt, but item {item_id} "
                    f"has style '{item.options.get('style')}'"
                )
    return None


def update_from_user_turn(verifier, conversation: list[dict], user_text: str) -> None:
    """Update persisted intent state after the latest customer turn."""
    previous = _state(verifier)
    if previous is None or not user_text or user_text.strip().startswith("###STOP###"):
        return
    from tau2.verifier.slm_helper import slm_extract_json

    db_facts = []
    db = getattr(verifier, "db", None)
    for order_id in sorted(set(re.findall(r"#W\d+", "\n".join(
        str(message.get("content", "")) for message in conversation[-20:]
    )))):
        try:
            order = db.orders.get(order_id) if db is not None else None
        except Exception:
            order = None
        if order is not None:
            db_facts.append(
                {"order_id": order_id, "status": str(getattr(order, "status", ""))}
            )

    question = (
        "Maintain the CURRENT retail action-request state from this conversation. "
        "The previous state is supplied below. Process the latest customer turn, "
        "including changes of mind, corrections, narrowing item lists, changing "
        "payment/address/order/variant, or cancelling an earlier request. Preserve "
        "unaffected requests. A revised decision supersedes the old request and MUST "
        "be awaiting_confirmation until the agent presents the revised exact details "
        "and the customer explicitly confirms them afterward. A generic yes confirms "
        "only the immediately preceding agent proposal. Do not infer confirmation from "
        "the initial request itself. Mark a request confirmed only from an explicit "
        "customer confirmation after an agent summary. Use these statuses only: "
        "gathering_details, awaiting_confirmation, confirmed, completed, cancelled. "
        "Do not invent IDs or details. Return the FULL updated state as one JSON object "
        "with keys latest_decision_summary and requests. Each request must have id, "
        "action, status, details, summary, confirmation_basis, supersedes. Valid actions: "
        + ", ".join(sorted(RETAIL_ACTION_TOOLS))
        + ".\nPrevious state:\n"
        + json.dumps(previous, sort_keys=True)
        + "\nRelevant database facts (authoritative; never invent alternatives):\n"
        + json.dumps(db_facts, sort_keys=True)
        + "\nLatest customer turn:\n"
        + user_text
    )
    try:
        candidate = slm_extract_json(question, conversation, max_tokens=900)
        updated = _validate_state(candidate, previous, user_text, db)
    except Exception as exc:
        logger.warning("Retail trace state extraction failed: %s", exc)
        updated = None
    if updated is None:
        logger.warning("Retail trace state extraction returned invalid state")
        updated = previous
    elif (
        previous.get("requests")
        and not updated.get("requests")
        and not _DECISION_CHANGE_RE.search(user_text)
    ):
        # An empty extraction must not erase active intent during authentication,
        # information gathering, or terse confirmations.
        updated["requests"] = previous["requests"]
    _apply_explicit_confirmation(updated, conversation, user_text)
    verifier._retail_trace_state = updated
    _write_state(verifier)


def _active_requests(state: dict, statuses: set[str]) -> list[dict]:
    return [r for r in state.get("requests", []) if r.get("status") in statuses]


def rule_write_matches_confirmed_request(
    tool_name,
    tool_args,
    conversation,
    db,
    verifier=None,
):
    """Block only a confidently identified action/detail mismatch."""
    if tool_name not in RETAIL_ACTION_TOOLS:
        return None
    state = _state(verifier)
    exact_confirmation = _has_exact_confirmation(tool_name, tool_args, conversation)
    if not exact_confirmation:
        return (
            "Trace confirmation required: before this write, present the exact "
            "action type and every proposed argument (target, complete item list, "
            "replacement IDs/options, payment/reason/address), ask for confirmation, "
            "and wait for an explicit unchanged yes. A customer's option selection "
            "or 'please proceed' is not a substitute for the agent's exact summary."
        )
    if state is not None:
        for request in _active_requests(
            state, {"gathering_details", "awaiting_confirmation"}
        ):
            request["status"] = "confirmed"
            request["confirmation_basis"] = "exact summarized proposal + explicit yes"
        _write_state(verifier)
    direct_mismatch = _direct_write_decision_check(
        tool_name, tool_args, conversation, db
    )
    if direct_mismatch:
        return (
            "Trace-derived mismatch with the latest customer decision: "
            f"{direct_mismatch}. Re-check the conversation and DB facts, present "
            "corrected exact details, and obtain confirmation again."
        )
    deterministic_mismatch = _deterministic_target_item_check(
        tool_name, tool_args, conversation, db
    )
    if deterministic_mismatch:
        return (
            "Trace-derived target mismatch: "
            f"{deterministic_mismatch}. Select the customer-requested existing "
            "item(s), present the corrected complete action, and reconfirm."
        )
    if state is None:
        return None
    return None


def record_successful_write(verifier, tool_name: str, tool_args: dict) -> None:
    """Mark the matching confirmed request completed after a successful write."""
    state = _state(verifier)
    if state is None:
        return
    state.setdefault("completed_writes", []).append(
        {"tool_name": tool_name, "tool_args": tool_args}
    )
    if tool_name == "transfer_to_human_agents":
        for request in _active_requests(
            state, {"gathering_details", "awaiting_confirmation", "confirmed"}
        ):
            request["status"] = "completed"
            request["completion"] = "transferred_to_human_agent"
        _write_state(verifier)
        return
    if tool_name not in RETAIL_ACTION_TOOLS:
        return
    candidates = [
        request for request in state.get("requests", [])
        if request.get("status") in {"confirmed", "awaiting_confirmation"}
        and request.get("action") == tool_name
    ]
    matched = []
    identifiers = {
        str(value)
        for key, value in tool_args.items()
        if key in {"order_id", "user_id"} and value
    }
    for request in candidates:
        request_text = json.dumps(request, sort_keys=True)
        if identifiers and any(identifier in request_text for identifier in identifiers):
            matched.append(request)
    if not matched and len(candidates) == 1:
        matched = candidates
    for request in matched:
        request["status"] = "completed"
        request["completed_tool_args"] = tool_args
    if matched:
        _write_state(verifier)


def conversation_complete(verifier, user_text: str) -> bool:
    """Recognize a terminal customer pleasantry after all work is resolved."""
    if not user_text or not re.search(
        r"\b(thank you|thanks|no(?:,)? i don'?t need|nothing else|"
        r"have a (?:great|good|fantastic) day|goodbye|bye)\b",
        user_text,
        re.IGNORECASE,
    ):
        return False
    state = _state(verifier)
    if state is None:
        return False
    active = _active_requests(
        state, {"gathering_details", "awaiting_confirmation", "confirmed"}
    )
    if not active:
        return True
    # Do not let an SLM-resurrected copy of an already completed write keep the
    # simulation alive after a clear customer goodbye.
    completed = state.get("completed_writes", [])
    for request in active:
        request_text = json.dumps(request, sort_keys=True)
        matched = False
        for write in completed:
            if write.get("tool_name") != request.get("action"):
                continue
            args = write.get("tool_args") or {}
            identifiers = [
                str(args.get(key)) for key in ("order_id", "user_id") if args.get(key)
            ]
            if not identifiers or any(value in request_text for value in identifiers):
                matched = True
                break
        if not matched:
            same_action = [
                write for write in completed
                if write.get("tool_name") == request.get("action")
            ]
            matched = len(same_action) == 1
        if not matched:
            return False
    return True


def completion_feedback(verifier) -> str | None:
    """Prevent agent stop while current actionable requests remain unresolved."""
    state = _state(verifier)
    if state is None:
        return None
    active = _active_requests(
        state, {"gathering_details", "awaiting_confirmation", "confirmed"}
    )
    if not active:
        return None
    summaries = "; ".join(
        f"{r['id']} [{r['status']}]: {r.get('summary') or r['action']}" for r in active
    )
    return (
        "Do not end the conversation yet. The persisted latest-decision state has "
        f"unresolved customer request(s): {summaries}. Re-read the latest decision. "
        "If it changed, summarize the revised exact details and obtain fresh "
        "confirmation; if already confirmed, complete the matching action."
    )


ALL_RULES = [rule_write_matches_confirmed_request]


def check_all(tool_name, tool_args, conversation, db, **kwargs) -> str | None:
    """Run opt-in trace-derived checks and return the first violation."""
    verifier = kwargs.get("verifier")
    for rule_fn in ALL_RULES:
        try:
            result = rule_fn(
                tool_name,
                tool_args,
                conversation,
                db,
                verifier=verifier,
            )
        except Exception as exc:
            logger.warning("Retail trace rule %s raised: %s", rule_fn.__name__, exc)
            continue
        if result is not None:
            logger.info("Retail trace rule %s violated: %s", rule_fn.__name__, result)
            return result
    return None