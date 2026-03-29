"""
ToolCallVerifier: Validates tool calls during simulation against a TaskSpec.

The verifier intercepts tool calls before/after execution and:
1. Checks if the tool call is allowed by the spec
2. Returns feedback if a violation is detected
3. Tracks all tool calls for stateful validation (e.g. required reads before writes)

Integration: The verifier wraps the orchestrator's _execute_tool_calls method.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage
from tau2.environment.toolkit import ToolType, get_tool_types
from tau2.verifier.spec import TaskSpec

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of verifying a tool call."""

    tool_name: str
    arguments: dict
    is_valid: bool
    feedback: str
    is_warning: bool = False  # True if valid but with advisory feedback


@dataclass
class VerificationLog:
    """Log of all verification results for a simulation."""

    task_id: str
    results: list[VerificationResult] = field(default_factory=list)
    violations: int = 0
    warnings: int = 0

    def add(self, result: VerificationResult):
        self.results.append(result)
        if not result.is_valid:
            self.violations += 1
        elif result.is_warning:
            self.warnings += 1

    def summary(self) -> dict:
        return {
            "task_id": self.task_id,
            "total_checks": len(self.results),
            "violations": self.violations,
            "warnings": self.warnings,
            "details": [
                {
                    "tool": r.tool_name,
                    "args": r.arguments,
                    "valid": r.is_valid,
                    "feedback": r.feedback,
                }
                for r in self.results
                if not r.is_valid or r.is_warning
            ],
        }


class ToolCallVerifier:
    """
    Validates tool calls against a TaskSpec during simulation.

    Usage:
        spec = get_spec(task_id)  # from airline_specs
        verifier = ToolCallVerifier(spec, tool_types)
        # During simulation, for each tool call:
        result = verifier.verify(tool_call)
        if not result.is_valid:
            # Return feedback instead of executing, or log and continue
    """

    def __init__(
        self,
        spec: TaskSpec,
        tool_types: dict[str, str],  # {tool_name: "READ"|"WRITE"|"GENERIC"}
        block_on_violation: bool = True,
        max_feedback_per_tool: int = 3,
    ):
        """
        Args:
            spec: The task specification to validate against.
            tool_types: Mapping of tool names to their types.
            block_on_violation: If True, violations produce error ToolMessages.
                If False, violations are logged but tool calls execute normally.
            max_feedback_per_tool: Max times to provide feedback for same tool
                before allowing it through (prevents infinite loops).
        """
        self.spec = spec
        self.tool_types = tool_types
        self.block_on_violation = block_on_violation
        self.max_feedback_per_tool = max_feedback_per_tool
        self.calls_so_far: list[dict] = []
        self.log = VerificationLog(task_id=spec.task_id)
        self._feedback_count: dict[str, int] = {}

    def verify(self, tool_call: ToolCall) -> VerificationResult:
        """
        Verify a single tool call against the spec.

        Args:
            tool_call: The tool call to verify.

        Returns:
            VerificationResult with is_valid=True if allowed, False with feedback if not.
        """
        tool_name = tool_call.name
        arguments = tool_call.arguments
        tool_type = self.tool_types.get(tool_name, "GENERIC")
        if isinstance(tool_type, ToolType):
            tool_type = tool_type.value.upper()

        is_valid, feedback = self.spec.validate_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            tool_type=tool_type,
            calls_so_far=self.calls_so_far,
        )

        # Check if we've already given enough feedback for this tool
        if not is_valid and self.block_on_violation:
            count = self._feedback_count.get(tool_name, 0)
            if count >= self.max_feedback_per_tool:
                logger.warning(
                    f"Verifier: max feedback reached for {tool_name}, allowing through"
                )
                is_valid = True
                feedback = ""
            else:
                self._feedback_count[tool_name] = count + 1

        # Determine if this is a warning (valid but with feedback)
        is_warning = is_valid and bool(feedback)

        result = VerificationResult(
            tool_name=tool_name,
            arguments=arguments,
            is_valid=is_valid,
            feedback=feedback,
            is_warning=is_warning,
        )
        self.log.add(result)

        # Track the call
        self.calls_so_far.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "tool_type": tool_type,
        })

        if not is_valid:
            logger.info(
                f"Verifier VIOLATION [task={self.spec.task_id}]: {tool_name}({arguments}) - {feedback}"
            )
        elif is_warning:
            logger.info(
                f"Verifier WARNING [task={self.spec.task_id}]: {tool_name}({arguments}) - {feedback}"
            )

        return result

    def make_feedback_message(
        self, tool_call: ToolCall, result: VerificationResult
    ) -> ToolMessage:
        """
        Create a ToolMessage with verification feedback (instead of executing the tool).

        This replaces the normal tool result when a violation is detected.
        """
        return ToolMessage(
            id=tool_call.id,
            role="tool",
            content=result.feedback,
            requestor=tool_call.requestor,
            error=True,
        )

    def get_summary(self) -> dict:
        """Get a summary of all verification results."""
        return self.log.summary()


def _load_spec_from_generated_json(task_id: str, domain: str) -> Optional[TaskSpec]:
    """Load a TaskSpec from the LLM-generated JSON specs file.

    The generated specs file lives at:
        data/tau2/domains/{domain}/generated_specs.json

    Returns None if the file doesn't exist or the task_id is not found.
    """
    from tau2.verifier.generate_specs import load_generated_specs
    from tau2.verifier.spec import ActionConstraint

    raw_specs = load_generated_specs(domain)
    if raw_specs is None:
        return None

    raw = raw_specs.get(str(task_id))
    if raw is None:
        return None

    # Convert JSON dict → TaskSpec
    allowed = []
    for a in raw.get("allowed_write_actions", []):
        allowed.append(
            ActionConstraint(
                tool_name=a["tool_name"],
                required_args=a.get("required_args", {}),
            )
        )

    # Forbidden write tools
    forbidden = set(raw.get("forbidden_write_tools", []))

    # If transfer_to_human is True, add transfer_to_human_agents to allowed
    if raw.get("transfer_to_human", False):
        if not any(a.tool_name == "transfer_to_human_agents" for a in allowed):
            allowed.append(ActionConstraint(tool_name="transfer_to_human_agents"))

    return TaskSpec(
        task_id=str(task_id),
        description=raw.get("reasoning", ""),
        forbidden_write_tools=forbidden,
        allowed_write_actions=allowed,
        max_write_calls=raw.get("max_write_calls"),
    )


def create_verifier_for_task(
    task_id: str,
    domain: str,
    environment,
    block_on_violation: bool = True,
    max_feedback_per_tool: int = 3,
) -> Optional[ToolCallVerifier]:
    """
    Create a ToolCallVerifier for a specific task.

    Loads specs from LLM-generated JSON files (generated_specs.json) which are
    produced from (user_scenario + policy) without using evaluation criteria.

    Falls back to legacy code-based specs if no generated JSON exists.

    Args:
        task_id: The task ID.
        domain: The domain name (e.g. "airline").
        environment: The Environment object (to get tool types).
        block_on_violation: Whether to block violated tool calls.
        max_feedback_per_tool: Max feedback attempts per tool.

    Returns:
        A ToolCallVerifier if a spec exists for this task, None otherwise.
    """
    # Try detailed specs first (highest quality — argument-level validation)
    spec = None
    if domain == "airline":
        try:
            from tau2.verifier.airline_specs_detailed import get_spec as get_detailed_spec
            spec = get_detailed_spec(task_id)
            logger.info(f"Loaded detailed spec for {domain} task {task_id}")
        except (ValueError, ImportError):
            pass
    elif domain == "retail":
        try:
            from tau2.verifier.retail_specs_detailed import get_spec as get_retail_detailed
            spec = get_retail_detailed(task_id)
            logger.info(f"Loaded detailed spec for {domain} task {task_id}")
        except (ValueError, ImportError):
            pass
    elif domain in ("telecom", "telecom-workflow"):
        try:
            from tau2.verifier.telecom_specs_detailed import get_spec as get_telecom_detailed
            spec = get_telecom_detailed(task_id)
            logger.info(f"Loaded detailed spec for {domain} task {task_id}")
        except (ValueError, ImportError):
            pass

    # Fall back to LLM-generated specs
    if spec is None:
        spec = _load_spec_from_generated_json(task_id, domain)
        if spec is not None:
            logger.info(f"Loaded generated spec for {domain} task {task_id}")

    if spec is None:
        # Fallback to legacy code-based specs
        logger.debug(
            f"No generated spec for {domain} task {task_id}, trying legacy specs"
        )
        if domain == "airline":
            from tau2.verifier.airline_specs import get_spec
            try:
                spec = get_spec(task_id)
            except ValueError:
                logger.warning(f"No spec found for airline task {task_id}")
                return None
        elif domain == "retail":
            from tau2.verifier.retail_specs import get_spec
            try:
                spec = get_spec(task_id)
            except ValueError:
                logger.warning(f"No spec found for retail task {task_id}")
                return None
        elif domain in ("telecom", "telecom-workflow"):
            from tau2.verifier.telecom_specs import get_spec
            try:
                spec = get_spec(task_id)
            except ValueError:
                logger.warning(f"No spec found for telecom task {task_id}")
                return None
        else:
            logger.info(f"No verifier specs available for domain: {domain}")
            return None

    tool_types = get_tool_types(environment.tools)

    return ToolCallVerifier(
        spec=spec,
        tool_types=tool_types,
        block_on_violation=block_on_violation,
        max_feedback_per_tool=max_feedback_per_tool,
    )
