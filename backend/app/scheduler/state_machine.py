"""The ONLY module allowed to mutate dose_event.state (AGENTS.md section 8).

    SCHEDULED -> SENT -> AWAITING_REPLY -> REMINDED_AGAIN
              -> {TAKEN | TAKEN_LATE | MISSED | SKIPPED}

Every transition is logged with the dose id (section 12). When the demo
misbehaves at 11pm these logs are the only tool that works.

Transitions are guarded: an illegal move is refused and logged rather than
silently applied. That is what stops a late webhook retry from dragging a
TAKEN dose back into REMINDED_AGAIN.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db import session_scope
from app.models import DOSE_TERMINAL_STATES, DoseEvent

log = logging.getLogger(__name__)

#: Which states each state may move to. Anything not listed is refused.
ALLOWED: dict[str, set[str]] = {
    "SCHEDULED": {"SENT", "SKIPPED", "MISSED"},
    "SENT": {"AWAITING_REPLY", "TAKEN", "SKIPPED", "REMINDED_AGAIN", "MISSED"},
    "AWAITING_REPLY": {"REMINDED_AGAIN", "TAKEN", "SKIPPED", "MISSED"},
    "REMINDED_AGAIN": {"MISSED", "TAKEN", "SKIPPED"},
    # A missed dose is the one terminal state that can still move: a late
    # confirmation reclassifies it (section 4.8).
    "MISSED": {"TAKEN_LATE"},
    "TAKEN": set(),
    "TAKEN_LATE": set(),
    "SKIPPED": set(),
}


class IllegalTransition(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _apply(dose_id: str, new_state: str, **fields) -> str | None:
    """Move one dose to `new_state`. Returns the previous state, or None if
    the move was refused or the dose is gone."""
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        if dose is None:
            log.warning("dose %s not found - transition to %s ignored",
                        dose_id, new_state)
            return None

        old = dose.state
        if new_state == old:
            log.debug("dose %s already %s - no-op", dose_id, new_state)
            return old

        if new_state not in ALLOWED.get(old, set()):
            log.warning("REFUSED %s -> %s for dose %s", old, new_state, dose_id)
            return None

        dose.state = new_state
        dose.updated_at = _now()
        for key, value in fields.items():
            setattr(dose, key, value)
        session.add(dose)
        session.commit()

    log.info("dose %s: %s -> %s", dose_id, old, new_state)
    return old


# --------------------------------------------------------------------------
# outbound side - driven by the ticker
# --------------------------------------------------------------------------


def mark_sent(dose_id: str) -> bool:
    """SCHEDULED -> SENT. Claimed BEFORE the reminder actually goes out.

    Claiming first is what makes invariant 5 hold: if the process dies
    mid-send, the restart finds the dose already SENT and never sends a second
    reminder. The cost is that a failed send leaves a dose marked SENT with
    nothing delivered - the follow-up at FOLLOWUP_MINUTES covers that case,
    and the failure is recorded in message_log.
    """
    return _apply(dose_id, "SENT", sent_at=_now()) is not None


def mark_awaiting_reply(dose_id: str) -> bool:
    """SENT -> AWAITING_REPLY, once Meta has accepted the message."""
    return _apply(dose_id, "AWAITING_REPLY") is not None


def mark_reminded_again(dose_id: str) -> bool:
    """-> REMINDED_AGAIN after FOLLOWUP_MINUTES of silence."""
    return _apply(dose_id, "REMINDED_AGAIN", followup_sent_at=_now()) is not None


def mark_missed(dose_id: str) -> bool:
    """-> MISSED after ESCALATE_MINUTES total. The caretaker alert follows."""
    return _apply(dose_id, "MISSED") is not None


def mark_caretaker_alerted(dose_id: str) -> None:
    """Record that the escalation actually reached the caretaker.

    Not a state change - it is how the ticker avoids alerting twice for the
    same missed dose.
    """
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        if dose is None:
            return
        dose.caretaker_alerted_at = _now()
        dose.updated_at = _now()
        session.add(dose)
        session.commit()
    log.info("dose %s: caretaker alerted", dose_id)


# --------------------------------------------------------------------------
# inbound side - driven by replies
# --------------------------------------------------------------------------


def mark_taken(dose_id: str, source: str, text: str | None = None) -> bool:
    """-> TAKEN. Ends the escalation chain."""
    return _apply(dose_id, "TAKEN", responded_at=_now(),
                  response_source=source, response_text=text) is not None


def mark_taken_late(dose_id: str, source: str, text: str | None = None) -> bool:
    """MISSED -> TAKEN_LATE on a late confirmation (section 4.8).

    The caretaker is told it resolved; that message is sent by the caller,
    because this module does not do I/O.
    """
    return _apply(dose_id, "TAKEN_LATE", responded_at=_now(),
                  response_source=source, response_text=text) is not None


def mark_skipped(dose_id: str, reason: str | None = None,
                 source: str = "text") -> bool:
    """-> SKIPPED when the patient explicitly declines this dose."""
    return _apply(dose_id, "SKIPPED", responded_at=_now(),
                  response_source=source, reason=reason) is not None


def confirm_taken(dose_id: str, source: str, text: str | None = None) -> str | None:
    """Record "I took it" without the caller needing to know the dose's state.

    Picks TAKEN or TAKEN_LATE based on where the dose actually is, which is the
    whole of section 4.8's reclassification rule. Returns the state it landed
    in, or None if the dose could not be moved.
    """
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        if dose is None:
            log.warning("confirm_taken: dose %s not found", dose_id)
            return None
        current = dose.state

    if current == "MISSED":
        return "TAKEN_LATE" if mark_taken_late(dose_id, source, text) else None
    if current in ("TAKEN", "TAKEN_LATE"):
        log.info("dose %s already %s - duplicate confirmation ignored",
                 dose_id, current)
        return current
    return "TAKEN" if mark_taken(dose_id, source, text) else None


def is_open(dose_id: str) -> bool:
    """True while a dose can still receive a reminder or a reply."""
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        return dose is not None and dose.state not in DOSE_TERMINAL_STATES
