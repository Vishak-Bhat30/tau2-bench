"""LLM-based pre-execution verifier for assistant tool calls.

Unlike the formal domain verifiers, this verifier asks a dedicated LLM to
judge every proposed assistant tool call against the complete visible
conversation, domain policy, and available tool schemas. A rejected call is
returned through the existing ``[VERIFIER]`` feedback path and is not executed
for that round.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are a strict customer-service tool-call verifier.

Judge the proposed assistant tool call using ONLY:
1. the domain policy,
2. the available tool definitions, and
3. the visible conversation and prior tool results.

Check all of the following:
- The tool is the correct action for the customer's LATEST decision. Later
  corrections, narrowing, cancellations, and changes of mind override earlier
  intent.
- Every argument is grounded in the conversation or prior tool results and
  matches the requested order/user/items/options/payment/address/reason.
- The call satisfies policy prerequisites, including authentication, order
  status, exact action-detail disclosure, and explicit confirmation when
  required.
- The tool schema is followed and no required argument is missing.
- The call is not a duplicate of an action already completed successfully.
- Read calls are relevant and do not access another customer's information.

Do not use hidden task expectations and do not invent facts. If the visible
evidence is insufficient to prove the call wrong, allow it. Block only for a
specific, actionable error.

Return exactly one JSON object and no markdown:
{"verdict":"allow","feedback":""}
or
{"verdict":"block","feedback":"Concise explanation of what is wrong and what the agent must do next."}
"""


class LLMToolCallVerifier:
    """Verify every assistant tool call with an OpenAI-compatible LLM."""

    requires_full_conversation = True

    def __init__(
        self,
        *,
        domain: str,
        policy: str,
        tools: list[Any],
        db=None,
    ):
        self.domain = domain
        self.policy = policy
        self.db = db
        self.api_base = os.getenv(
            "TAU2_LLM_VERIFIER_API_BASE", "http://127.0.0.1:3141/v1"
        )
        self.api_key = os.getenv("TAU2_LLM_VERIFIER_API_KEY", "dummy")
        self.model = os.getenv("TAU2_LLM_VERIFIER_MODEL", "gpt-5.6-sol")
        self.fail_closed = os.getenv("TAU2_LLM_VERIFIER_FAIL_CLOSED", "0") == "1"
        self.max_tokens = int(os.getenv("TAU2_LLM_VERIFIER_MAX_TOKENS", "500"))
        self.tool_schemas = [tool.openai_schema for tool in tools]
        self._called_all_tools: list[str] = []
        self._completed_calls: list[dict[str, Any]] = []

    @staticmethod
    def _parse_response(text: str) -> dict[str, str] | None:
        cleaned = (text or "").strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if fenced:
            cleaned = fenced.group(1)
        else:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        verdict = str(parsed.get("verdict", "")).strip().lower()
        if verdict not in {"allow", "block"}:
            return None
        return {
            "verdict": verdict,
            "feedback": str(parsed.get("feedback", "")).strip(),
        }

    def _request_payload(
        self,
        tool_name: str,
        tool_args: dict,
        conversation: list[dict],
    ) -> str:
        return json.dumps(
            {
                "domain": self.domain,
                "policy": self.policy,
                "available_tools": self.tool_schemas,
                "conversation_so_far": conversation,
                "proposed_tool_call": {
                    "name": tool_name,
                    "arguments": tool_args,
                },
                "successfully_completed_calls": self._completed_calls,
            },
            ensure_ascii=True,
            default=str,
        )

    def verify(
        self,
        tool_name: str,
        tool_args: dict,
        conversation: list[dict],
    ) -> str | None:
        """Return verifier feedback to block, or ``None`` to allow execution."""
        try:
            from openai import OpenAI

            client = OpenAI(base_url=self.api_base, api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": self._request_payload(
                            tool_name, tool_args, conversation
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=self.max_tokens,
            )
            raw = response.choices[0].message.content or ""
            verdict = self._parse_response(raw)
            if verdict is None:
                raise ValueError(f"Invalid verifier response: {raw[:300]!r}")
        except Exception as exc:
            logger.warning("LLM tool-call verifier failed: %s", exc)
            if self.fail_closed:
                return (
                    "[VERIFIER] LLM verifier unavailable or returned an invalid "
                    "decision. Do not execute this call yet; retry after verification."
                )
            return None

        if verdict["verdict"] == "allow":
            logger.info("LLM verifier allowed %s", tool_name)
            return None

        feedback = verdict["feedback"] or (
            "The proposed call is not justified by the latest conversation and policy."
        )
        logger.info("LLM verifier blocked %s: %s", tool_name, feedback)
        return f"[VERIFIER] LLM verifier blocked this call: {feedback}"

    def record_tool_call(self, tool_name: str, tool_args: dict | None = None) -> None:
        """Record calls only after successful execution for duplicate detection."""
        self._called_all_tools.append(tool_name)
        self._completed_calls.append(
            {"name": tool_name, "arguments": tool_args or {}}
        )

    def check_result(self, tool_name: str, tool_args: dict, result_content: str):
        return None
