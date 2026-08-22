"""Produce and send the one short warm reply for an Intent.

Style rules (AGENTS.md section 11): one idea per message, the reader is 68 and
reading slowly. Names the medicine and strength every time. Never scolds - a
missed dose gets warmth and a second chance. Replies in whatever language the
patient used.

Every outbound message passes through guardrails.check() first, with no
exceptions.
"""

from __future__ import annotations

_PHASE = "Phase 3 - agent understanding"


async def respond(intent, patient) -> None:
    """Handle one Intent end to end: transition the dose if needed, build the
    reply, run it through the guardrails, and send it.

    For `kind == "question"`, the ONLY knowledge source is
    knowledge.get_confirmed(). If that returns None the agent says it does not
    have confirmed information yet and offers to notify the caretaker - it
    never falls back to asking Qwen directly (invariant 9).
    """
    raise NotImplementedError(_PHASE)
