"""
TaskSpec: Declarative specification for validating tool calls during a simulation.

Each spec encodes:
- Which WRITE tool calls are allowed (with argument constraints)
- Which WRITE tool calls are forbidden
- Which READ calls should precede any WRITE
- Custom validation logic per task
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ActionConstraint:
    """Constraint on a specific tool call."""

    tool_name: str
    required_args: dict = field(default_factory=dict)  # args that MUST match
    compare_args: list[str] | None = None  # which args to compare (None = all in required_args)
    description: str = ""


@dataclass
class TaskSpec:
    """
    Specification for validating tool calls for a single task.

    Attributes:
        task_id: The task identifier (e.g. "0", "1", ..., "49").
        description: Human-readable description of what the task tests.
        forbidden_write_tools: Set of WRITE tool names that must NEVER be called.
            If a tool in this set is invoked, the verifier returns an error.
        allowed_write_actions: List of ActionConstraints for WRITE tools that are
            expected/allowed. If empty and forbidden is also empty, any write is allowed.
        required_reads_before_writes: List of READ tool calls that should happen
            before any WRITE. Used for advisory warnings, not hard blocks.
        forbidden_certificates: If True, send_certificate must not be called.
        max_write_calls: Maximum number of WRITE tool calls allowed. None = unlimited.
        notes: Additional notes for the verifier about this task.
    """

    task_id: str
    description: str = ""
    forbidden_write_tools: set[str] = field(default_factory=set)
    allowed_write_actions: list[ActionConstraint] = field(default_factory=list)
    required_reads_before_writes: list[ActionConstraint] = field(default_factory=list)
    forbidden_certificates: bool = False
    max_write_calls: int | None = None
    notes: str = ""

    def validate_tool_call(
        self,
        tool_name: str,
        arguments: dict,
        tool_type: str,
        calls_so_far: list[dict],
    ) -> tuple[bool, str]:
        """
        Validate a tool call against this spec.

        Args:
            tool_name: Name of the tool being called.
            arguments: Arguments passed to the tool.
            tool_type: "READ", "WRITE", or "GENERIC".
            calls_so_far: List of previous tool calls in this simulation.

        Returns:
            (is_valid, feedback) — True if valid, or False with feedback string.
        """
        # READ and GENERIC tools are always allowed
        if tool_type in ("READ", "GENERIC"):
            return True, ""

        # Check forbidden WRITE tools
        if tool_name in self.forbidden_write_tools:
            return False, self._forbidden_feedback(tool_name)

        # Check forbidden certificates
        if self.forbidden_certificates and tool_name == "send_certificate":
            return False, (
                f"[VERIFIER] send_certificate is not allowed for this task. "
                f"Task context: {self.description}"
            )

        # Check max write calls
        if self.max_write_calls is not None:
            write_calls = [c for c in calls_so_far if c.get("tool_type") == "WRITE"]
            if len(write_calls) >= self.max_write_calls:
                return False, (
                    f"[VERIFIER] Maximum number of WRITE calls ({self.max_write_calls}) "
                    f"already reached. No more WRITE operations allowed."
                )

        # Check required reads before writes
        read_warnings = self._check_required_reads(calls_so_far)

        # If we have allowed_write_actions, check that this call matches one of them
        if self.allowed_write_actions:
            match_result = self._check_allowed_writes(tool_name, arguments)
            if not match_result[0]:
                feedback = match_result[1]
                if read_warnings:
                    feedback = read_warnings + "\n" + feedback
                return False, feedback

        if read_warnings:
            # Return valid but with advisory warning
            return True, read_warnings

        return True, ""

    def _forbidden_feedback(self, tool_name: str) -> str:
        """Generate feedback for a forbidden tool call."""
        action_map = {
            "cancel_reservation": "Cancellation is not allowed for this scenario.",
            "send_certificate": "Compensation/certificate is not appropriate for this scenario.",
            "book_reservation": "Booking is not expected for this scenario.",
            "update_reservation_flights": "Flight modification is not allowed for this scenario.",
            "update_reservation_baggages": "Baggage modification is not allowed for this scenario.",
            "update_reservation_passengers": "Passenger modification is not allowed for this scenario.",
        }
        reason = action_map.get(tool_name, f"{tool_name} is not allowed for this scenario.")
        return (
            f"[VERIFIER] FORBIDDEN: {tool_name} should not be called. "
            f"{reason} "
            f"Task context: {self.description} "
            f"Please reconsider your approach and re-read the policy."
        )

    def _check_required_reads(self, calls_so_far: list[dict]) -> str:
        """Check if required READ calls have been made before this WRITE."""
        if not self.required_reads_before_writes:
            return ""

        completed_reads = {
            (c["tool_name"], frozenset(c.get("arguments", {}).items()))
            for c in calls_so_far
            if c.get("tool_type") == "READ"
        }

        missing = []
        for req in self.required_reads_before_writes:
            found = False
            for name, args_frozen in completed_reads:
                if name == req.tool_name:
                    if req.required_args:
                        actual_args = dict(args_frozen)
                        if all(
                            actual_args.get(k) == v
                            for k, v in req.required_args.items()
                        ):
                            found = True
                            break
                    else:
                        found = True
                        break
            if not found:
                arg_str = ", ".join(f"{k}={v}" for k, v in req.required_args.items())
                missing.append(f"{req.tool_name}({arg_str})")

        if missing:
            return (
                f"[VERIFIER WARNING] Before making WRITE operations, you should first "
                f"call these READ operations to verify information: {', '.join(missing)}. "
                f"Please look up the relevant details before proceeding."
            )
        return ""

    def _check_allowed_writes(
        self, tool_name: str, arguments: dict
    ) -> tuple[bool, str]:
        """Check if a WRITE tool call matches one of the allowed actions."""
        # Find matching allowed actions by tool name
        matching = [a for a in self.allowed_write_actions if a.tool_name == tool_name]

        if not matching:
            allowed_names = {a.tool_name for a in self.allowed_write_actions}
            return False, (
                f"[VERIFIER] {tool_name} is not in the expected WRITE operations for this task. "
                f"Expected write tools: {', '.join(sorted(allowed_names))}. "
                f"Task context: {self.description}"
            )

        # Check if arguments match any of the allowed actions
        for action in matching:
            if not action.required_args:
                return True, ""

            compare_keys = action.compare_args or list(action.required_args.keys())
            match = True
            mismatches = []
            for key in compare_keys:
                expected = action.required_args.get(key)
                actual = arguments.get(key)
                if expected is not None and actual != expected:
                    match = False
                    mismatches.append(
                        f"  {key}: expected={expected!r}, got={actual!r}"
                    )

            if match:
                return True, ""

        # None of the allowed actions matched — provide detailed feedback
        feedback_parts = [
            f"[VERIFIER] {tool_name} arguments don't match expected values.",
        ]
        for action in matching:
            if action.description:
                feedback_parts.append(f"  Expected: {action.description}")
            feedback_parts.append(f"  Required args: {action.required_args}")
        feedback_parts.append(f"  Your args: {arguments}")
        feedback_parts.append("Please verify the arguments and try again.")

        return False, "\n".join(feedback_parts)
