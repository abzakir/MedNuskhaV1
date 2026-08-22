"""Every patient-facing string, in Urdu and English (invariant 12).

No inline copy in business logic - ever. Business code calls t(key, lang).

Urdu and English are core, not bolted on (AGENTS.md section 3.2): every key
exists in both languages from the moment it is added. Filled in during
Phase 3, when the agent starts producing messages.
"""

from __future__ import annotations

_PHASE = "Phase 3 - agent understanding"

DEFAULT_LANGUAGE = "ur"

#: key -> {"ur": ..., "en": ...}
#: Populated in Phase 3. The two entries below are fixed copy quoted verbatim
#: in AGENTS.md section 11 and must not be reworded.
STRINGS: dict[str, dict[str, str]] = {
    "refusal_clinical": {
        "ur": (
            "Main ye faisla nahi kar sakta - ye doctor sahab ka kaam hai. "
            "Main abhi {caretaker} ko bata deta hoon, aur ye baat aap ki agli "
            "report mein bhi likh di jayegi."
        ),
        "en": (
            "I cannot make that decision - that is the doctor's call. I am "
            "telling {caretaker} now, and it will also be noted in your next "
            "report."
        ),
    },
}


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Look up a string in the patient's language and format it.

    Falls back to Urdu when the language is unknown. Raises KeyError on a
    missing key rather than returning the key - a missing string is a bug we
    want to see in dev, not silently ship to a 68-year-old.
    """
    raise NotImplementedError(_PHASE)
