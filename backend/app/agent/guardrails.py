"""Programmatic safety check on every outbound message, before it is sent.

Invariant 8: the agent never diagnoses, changes a dose, recommends or
substitutes a medicine, or interprets a symptom or test result. Enforced in
three places - the system prompt, this module, and tests/test_guardrails.py.

This module is the layer that does not depend on a model behaving. A prompt can
be talked around; a regex over the final text cannot be. Everything here runs
on the OUTBOUND draft, after the model has spoken and before the patient sees
it, which is the only point where blocking still helps.

Deliberately conservative. A false block costs one unhelpful-but-safe message
and a caretaker notification. A false pass costs an elderly patient acting on
made-up medical advice. Those are not comparable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.i18n import strings

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# emergencies - checked on INBOUND text (section 11)
# --------------------------------------------------------------------------

EMERGENCY_PATTERNS = [
    # Urdu script
    r"سینے\s*میں\s*درد", r"سانس", r"بیہوش", r"خون",
    # Roman Urdu
    r"\bseen?e\s*(mein|me|m)\s*dard\b", r"\bchaati\s*(mein|me)\s*dard\b",
    r"\bsaans\b", r"\bsans\s*(nahi|nhi|band)\b", r"\bdam\s*ghut\b",
    r"\bbehosh\b", r"\bbe\s*hosh\b", r"\bghash\b",
    r"\bkhoon\b", r"\bkhun\s*(aa|beh|nikal)", r"\bfalij\b",
    # English
    r"\bchest\s*pain\b", r"\bcan'?t\s*breathe\b", r"\bcannot\s*breathe\b",
    r"\bbreathing\s*(problem|trouble|difficult)", r"\bunconscious\b",
    r"\bfaint(ed|ing)?\b", r"\bbleeding\b", r"\bstroke\b", r"\bseizure\b",
    r"\bcollapsed?\b",
]
_EMERGENCY_RE = re.compile("|".join(EMERGENCY_PATTERNS), re.IGNORECASE)

# --------------------------------------------------------------------------
# clinical overreach - checked on the OUTBOUND draft
# --------------------------------------------------------------------------

#: Telling someone to change how much they take.
DOSE_CHANGE_PATTERNS = [
    r"\b(do|2|teen|3|char|4|double|dugni|aadhi|half|adhi)\s*(goli|goliyan|tablet|khurak|dose)",
    r"\b(goli|tablet|dose|khurak)\s*(barha|barhaa|bara\s*dein|kam\s*kar|double|half)",
    r"\bincrease\s+(the\s+)?(dose|dosage)", r"\bdecrease\s+(the\s+)?(dose|dosage)",
    r"\bdouble\s+(the\s+)?(dose|dosage)", r"\bhalve\s+(the\s+)?(dose|dosage)",
    # Every tense, because "hypothetically, if someone TOOK two tablets" is
    # the same instruction with a hop in it - and that framing is exactly how
    # a model gets talked around its system prompt.
    r"\b(take|takes|taking|took|taken)\s+(a\s+)?(one|two|three|four|five|couple|\d+)"
    r"\s+(more\s+|extra\s+)?(tablets?|pills?|doses?|goli|goliyan)\b",
    r"\b(one|two|three|four|five|\d+)\s+(more\s+|extra\s+)?(tablets?|pills?|doses?)"
    r"\s+(is|are|would\s+be|hoga|hogi)\s+(fine|ok|okay|safe|theek)\b",
    r"\bskip\s+(the\s+)?(dose|tablet|medicine)\b",
    r"\bziyada\s*(lein|le\s*lo|le\s*lena)\b", r"\bkam\s*(lein|le\s*lo)\b",
]

#: Telling someone to start, stop or swap a medicine.
MEDICATION_CHANGE_PATTERNS = [
    r"\bstop\s+(taking|the\s+medicine|it)\b", r"\bband\s*kar\s*(dein|do|den)\b",
    r"\bshuru\s*kar\s*(dein|do|den)\b", r"\bstart\s+taking\b",
    r"\b(instead\s+of|iske\s*bajaye|iski\s*jagah)\b",
    r"\btry\s+(taking\s+)?(a\s+)?different\b", r"\bkoi\s*aur\s*dawai\b",
    r"\bswitch\s+to\b", r"\breplace\s+(it|the\s+medicine)\b",
    r"\byou\s+(should|can|could)\s+(take|use|try)\s+\w+\s*(instead|rather)",
]

#: Naming a condition, or explaining what a symptom means.
DIAGNOSIS_PATTERNS = [
    r"\byou\s+(probably\s+|likely\s+|may\s+|might\s+)?have\s+\w+",
    r"\b(aap\s*ko|apko)\s+\w+\s*(hai|ho\s*(gaya|gayi|raha))\b",
    r"\bit\s+(sounds|seems|looks)\s+like\s+(you|a|an)\b",
    r"\byeh\s+\w*\s*(bimari|marz)\s+hai\b",
    r"\bthis\s+is\s+(a\s+)?(symptom|sign)\s+of\b",
    r"\b(ki|ka)\s*nishani\s*hai\b",
    r"\bdiagnos(is|ed|e)\b",
    r"\b(sugar|blood\s*pressure|bp)\s+(zyada|ziyada|kam|high|low)\s+hai\b",
    r"\byour\s+(sugar|bp|blood\s*pressure)\s+is\s+(too\s+)?(high|low)\b",
    r"\bnormal\s+hai\b", r"\bthat'?s\s+normal\b", r"\bfikr\s*ki\s*baat\s*nahi\b",
]

_RULES: list[tuple[str, re.Pattern]] = [
    ("dose_change", re.compile("|".join(DOSE_CHANGE_PATTERNS), re.IGNORECASE)),
    ("medication_change", re.compile("|".join(MEDICATION_CHANGE_PATTERNS), re.IGNORECASE)),
    ("diagnosis", re.compile("|".join(DIAGNOSIS_PATTERNS), re.IGNORECASE)),
]

#: Numbers with a unit, e.g. "500mg", "2 tablets". Checked against the
#: patient's actual schedule (invariant 10).
_DOSE_FIGURE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mg|ml|mcg|g|gram|grams|goli|goliyan|tablets?|pills?|drops?|qatre)\b",
    re.IGNORECASE,
)


@dataclass
class GuardrailResult:
    """Outcome of checking one draft message."""

    allowed: bool
    #: The message to actually send - the draft when allowed, the fixed
    #: refusal when not.
    message: str
    #: Which rule fired, for the log and for the caretaker alert.
    violated_rule: str | None = None
    #: True when the caretaker must be notified regardless of the reply.
    alert_caretaker: bool = False


def is_emergency(text: str) -> bool:
    """True if the inbound text trips an emergency keyword in any language."""
    return bool(text and _EMERGENCY_RE.search(text))


#: A patient ASKING to change their medicine or dose. Checked on the way IN.
#:
#: The rules above check what we are about to SAY, which is the right place to
#: stop the agent inventing advice. But a question like "can I take Panadol
#: twice?" produces no unsafe text of its own - the agent simply answers
#: something unhelpful - so nothing fires and the patient never gets the
#: refusal section 11 requires. Measured on a real phone, 2026-08-23.
ASK_TO_CHANGE_PATTERNS = [
    # Urdu script
    r"دو\s*بار", r"دو\s*گولی", r"زیادہ\s*(لے|کھا)", r"آدھی\s*گولی",
    r"بند\s*کر\s*(دوں|سکت)", r"چھوڑ\s*(دوں|سکت)", r"بڑھا\s*(دوں|سکت)",
    # Roman Urdu - "kya main ... le lun / kha lun / sakta hoon"
    r"\b(do|2|teen|3|char|4)\s*(goli|goliyan|bar|baar|dafa|tablet)",
    r"\b(aadhi|adhi|half)\s*(goli|tablet)",
    r"\b(ziyada|zyada|extra)\s*(le|kha|lay)",
    r"\bband\s*kar\s*(dun|doon|sakt|lun)",
    r"\bchor\s*(dun|doon|sakt)", r"\bchhor\s*(dun|doon|sakt)",
    r"\bbarha\s*(dun|doon|sakt)", r"\bkam\s*kar\s*(dun|doon|sakt)",
    r"\bskip\s*kar", r"\bmiss\s*kar",
    # English
    r"\bcan\s+i\s+(take|have)\s+(two|three|four|\d+|more|extra|another)",
    r"\bshould\s+i\s+(take|stop|skip|double|increase|decrease)",
    r"\bcan\s+i\s+(stop|skip|double|increase|decrease|halve)",
    r"\bis\s+it\s+ok(ay)?\s+to\s+(take|stop|skip|double)",
    r"\btake\s+(it\s+)?twice\b", r"\bdouble\s+(the\s+)?dose",
]
_ASK_CHANGE_RE = re.compile("|".join(ASK_TO_CHANGE_PATTERNS), re.IGNORECASE)


def asks_to_change_medication(text: str) -> bool:
    """True when the PATIENT is asking to change a dose or a medicine.

    Deliberately fires on questions as well as statements: "kya main do goli le
    lun?" and "main do goli le raha hoon" both need a human, and neither is
    something the agent may answer.
    """
    return bool(text and _ASK_CHANGE_RE.search(text))


def dose_figures(text: str) -> set[str]:
    """Every "number + unit" in a piece of text, normalised for comparison."""
    return {f"{num.rstrip('0').rstrip('.') if '.' in num else num}"
            f"{unit.lower().rstrip('s')}"
            for num, unit in _DOSE_FIGURE_RE.findall(text or "")}


def contains_unknown_dose_figure(draft: str, known_texts: list[str]) -> str | None:
    """Invariant 10: no outbound message contains a dose figure not in the DB.

    `known_texts` is whatever the database actually holds for this patient -
    medicine names, strengths, schedule notes. Returns the offending figure, or
    None when every figure in the draft is accounted for.
    """
    in_draft = dose_figures(draft)
    if not in_draft:
        return None

    known: set[str] = set()
    for text in known_texts:
        known |= dose_figures(text)

    for figure in in_draft:
        if figure not in known:
            return figure
    return None


def check(draft: str, patient=None, intent=None,
          known_texts: list[str] | None = None,
          caretaker_name: str = "aap ke ghar walon") -> GuardrailResult:
    """Check one outbound draft. Called on every message, with no exceptions.

    `known_texts` should carry the patient's medicine names, strengths and any
    confirmed food rules, so a legitimate "Panadol 500mg" is not mistaken for
    an invented dose figure.
    """
    lang = getattr(patient, "language", None) or strings.DEFAULT_LANGUAGE
    text = draft or ""

    def refuse(rule: str) -> GuardrailResult:
        log.warning("GUARDRAIL BLOCKED (%s): %r", rule, text[:160])
        return GuardrailResult(
            allowed=False,
            message=strings.t("refusal_clinical", lang, caretaker=caretaker_name),
            violated_rule=rule,
            alert_caretaker=True,
        )

    if not text.strip():
        return refuse("empty_draft")

    for rule_name, pattern in _RULES:
        match = pattern.search(text)
        if match:
            log.warning("guardrail %s matched %r", rule_name, match.group(0))
            return refuse(rule_name)

    offending = contains_unknown_dose_figure(text, known_texts or [])
    if offending:
        log.warning("guardrail unknown_dose_figure matched %r", offending)
        return refuse("unknown_dose_figure")

    return GuardrailResult(allowed=True, message=text)


def emergency_response(patient=None, caretaker_name: str = "aap ke ghar walon"
                       ) -> GuardrailResult:
    """The fixed emergency copy, plus a caretaker alert.

    Section 11 requires that an emergency keyword produces this and nothing
    else - the model never gets to improvise on a chest pain message.
    """
    lang = getattr(patient, "language", None) or strings.DEFAULT_LANGUAGE
    return GuardrailResult(
        allowed=True,
        message=strings.t("emergency", lang, caretaker=caretaker_name),
        violated_rule="emergency",
        alert_caretaker=True,
    )
