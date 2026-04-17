"""M4 — typed event taxonomy.

Role: one authoritative list of every event kind on the bus and in the
ledger. Prevents stringly-typed drift. Defined early (M1 scaffold) even
though only a few kinds are in use before M4.
Produces: event-class definitions.
Consumes: nothing.

Every event carries `kind` (matching the class name), `actor`, `payload` dict,
and optional `parent_id` linking to the causing event.
"""

from __future__ import annotations

from enum import StrEnum


class Kind(StrEnum):
    # M1
    DAEMON_STARTED = "DaemonStarted"
    DAEMON_STOPPED = "DaemonStopped"
    INTENT_CREATED = "IntentCreated"

    # M3
    PLAN_PROPOSED = "PlanProposed"
    TASK_ASSIGNED = "TaskAssigned"
    PATCH_SUBMITTED = "PatchSubmitted"
    VERIFICATION_PASSED = "VerificationPassed"
    VERIFICATION_FAILED = "VerificationFailed"
    DECISION_RECORDED = "DecisionRecorded"

    # M6
    PROMPT_VARIANT_CANDIDATE = "PromptVariantCandidate"
    TOOL_PROPOSED = "ToolProposed"

    # M7
    DEVICE_HEARTBEAT = "DeviceHeartbeat"
    TASK_CLAIMED = "TaskClaimed"
    TASK_RELEASED = "TaskReleased"
