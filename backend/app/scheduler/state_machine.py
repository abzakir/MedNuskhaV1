"""The ONLY module allowed to mutate dose_event.state (AGENTS.md section 8).

Transitions:
    SCHEDULED -> SENT -> AWAITING_REPLY -> REMINDED_AGAIN
              -> {TAKEN | TAKEN_LATE | MISSED | SKIPPED}

Every transition is logged with the dose id (section 12) - these logs are the
only debugging tool that works when the demo misbehaves at 11pm.
"""

from __future__ import annotations

_PHASE = "Phase 2 - the dose loop"


def mark_sent(dose_id: str) -> None:
    """SCHEDULED -> SENT, then immediately AWAITING_REPLY once Meta accepts."""
    raise NotImplementedError(_PHASE)


def mark_reminded_again(dose_id: str) -> None:
    """AWAITING_REPLY -> REMINDED_AGAIN after FOLLOWUP_MINUTES of silence."""
    raise NotImplementedError(_PHASE)


def mark_taken(dose_id: str, source: str, text: str | None = None) -> None:
    """-> TAKEN. Cancels the escalation chain. `source` is one of
    RESPONSE_SOURCES: button, text, voice."""
    raise NotImplementedError(_PHASE)


def mark_taken_late(dose_id: str, source: str, text: str | None = None) -> None:
    """MISSED -> TAKEN_LATE on a late confirmation (section 4.8), and notify
    the caretaker that it resolved."""
    raise NotImplementedError(_PHASE)


def mark_missed(dose_id: str) -> None:
    """REMINDED_AGAIN -> MISSED after ESCALATE_MINUTES total. Triggers the
    caretaker_alert template."""
    raise NotImplementedError(_PHASE)


def mark_skipped(dose_id: str, reason: str | None = None) -> None:
    """-> SKIPPED when the patient explicitly declines this dose."""
    raise NotImplementedError(_PHASE)
