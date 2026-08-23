"""Every patient-facing string, in Urdu and English (invariant 12).

No inline copy in business logic - ever. Business code calls `t(key, lang)`.

These used to live in WhatsApp Manager as Meta templates. Since the switch to
GREEN-API (2026-08-22) there are no server-side templates and no approval
queue, so the bodies live here and are rendered locally. That is strictly
better: the copy is now version-controlled, reviewable in a diff, and
changeable without waiting hours for Meta.

Style rules from AGENTS.md section 11, applied to every string below:
  * one idea per message - the reader is 68 and reading slowly
  * the medicine and its strength are named every time
  * never scold; a missed dose gets warmth and a second chance

Language keys:
  "ur" - Roman Urdu, matching the copy in section 10. This is what a Pakistani
         family actually types to each other on WhatsApp, and the caretaker
         can read it too.
  "en" - English.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "ur"
LANGUAGES = ("ur", "en")


STRINGS: dict[str, dict[str, str]] = {

    # ------------------------------------------------------------------
    # dose flow
    # ------------------------------------------------------------------
    "dose_reminder": {
        "ur": "{name} ji, {hour} baj gaye - {medicine} lene ka waqt hai. {note}",
        "en": "{name} ji, it's {hour} o'clock - time to take {medicine}. {note}",
    },
    "dose_followup": {
        "ur": "{name} ji, sirf yaad dila rahe hain - {medicine} abhi baaki hai.",
        "en": "{name} ji, just a gentle reminder - {medicine} is still pending.",
    },
    "dose_taken_ack": {
        "ur": "Shukriya {name} ji. {medicine} le li - likh liya hai.",
        "en": "Thank you {name} ji. {medicine} taken - it's noted.",
    },
    "dose_late_ack": {
        "ur": "Shukriya {name} ji, likh liya hai. Der se hi sahi - achha kiya.",
        "en": "Thank you {name} ji, it's noted. Late is much better than not at all.",
    },
    "dose_later_ack": {
        "ur": "Theek hai {name} ji. Thori der mein dobara yaad dila denge.",
        "en": "That's alright {name} ji. We'll remind you again shortly.",
    },

    # Button labels. Max 25 characters (Green API limit).
    "btn_taken": {"ur": "Le li", "en": "Taken"},
    "btn_later": {"ur": "Abhi nahi", "en": "Not yet"},

    # ------------------------------------------------------------------
    # caretaker
    # ------------------------------------------------------------------
    "caretaker_alert": {
        "ur": ("{patient} ne aaj {hour} baje ki {medicine} confirm nahi ki. "
               "Do baar yaad dilaya gaya hai."),
        "en": ("{patient} has not confirmed the {hour} o'clock {medicine} today. "
               "Two reminders have been sent."),
    },
    "caretaker_late_resolved": {
        "ur": ("{patient} ne abhi {medicine} lene ki tasdeeq kar di hai - thori "
               "der se. Ye aap ki agli report mein bhi likha jayega."),
        "en": ("{patient} has now confirmed taking {medicine} - a little late. "
               "This will appear in your next report."),
    },
    "caretaker_emergency": {
        "ur": ("Zaroori: {patient} ne abhi likha hai - \"{words}\". Bara-e-meherbani "
               "foran raabta karein."),
        "en": ("Urgent: {patient} has just written - \"{words}\". Please get in "
               "touch immediately."),
    },

    # ------------------------------------------------------------------
    # caretaker commands - the caretaker talking TO us on WhatsApp
    # ------------------------------------------------------------------
    "care_help": {
        "ur": ("Main MedNuskha hoon. Aap mujhe ye likh sakte hain:\n"
               "- status : aaj ki report\n"
               "- rok dein : yaad-dahani band\n"
               "- shuru karein : dobara chalu\n"
               "Dawai add ya edit karne ke liye website kholein."),
        "en": ("This is MedNuskha. You can send me:\n"
               "- status : today's report\n"
               "- pause : stop reminders\n"
               "- resume : start them again\n"
               "To add or edit a medicine, open the website."),
    },
    "care_status": {
        "ur": "{patient} ki aaj ki report:\nLi: {taken} / {total}\n{lines}",
        "en": "{patient} today:\nTaken: {taken} / {total}\n{lines}",
    },
    "care_status_none": {
        "ur": "{patient} ke liye aaj koi dawai ka waqt nahi hai.",
        "en": "No doses are scheduled for {patient} today.",
    },
    "care_paused": {
        "ur": ("Theek hai. {patient} ki yaad-dahani rok di hai. Dobara chalu "
               "karne ke liye \"shuru karein\" likhein."),
        "en": ("Done. Reminders for {patient} are paused. Send \"resume\" to "
               "start them again."),
    },
    "care_resumed": {
        "ur": "{patient} ki yaad-dahani dobara chalu kar di hai.",
        "en": "Reminders for {patient} are running again.",
    },
    "care_no_patient": {
        "ur": ("Aap ne abhi tak koi mareez add nahi kiya. Website par ja kar "
               "add karein."),
        "en": "You haven't added anyone yet. Add them on the website.",
    },
    "care_which_patient": {
        "ur": "Kis ke baare mein? {names}",
        "en": "Which one? {names}",
    },
    "care_unclear": {
        "ur": ("Maaf kijiye ga, samajh nahi aaya. \"help\" likhein to main "
               "bata dun ke kya likh sakte hain."),
        "en": ("Sorry, I didn't understand. Send \"help\" and I'll list what "
               "you can ask."),
    },
    #: A caretaker asking a clinical question gets the same refusal a patient
    #: does - being the carer does not make the agent a doctor (invariant 8).
    "care_refusal": {
        "ur": ("Ye faisla main nahi kar sakta - ye doctor sahab ka kaam hai. "
               "Aap {patient} ke doctor se raabta karein. Main ne ye baat "
               "report mein likh di hai."),
        "en": ("I can't make that decision - that is the doctor's call. Please "
               "contact {patient}'s doctor. I've noted it in the report."),
    },

    # ------------------------------------------------------------------
    # onboarding
    # ------------------------------------------------------------------
    "patient_optin": {
        "ur": ("Assalam-o-alaikum {name} ji. {caretaker} ne aap ke liye dawai ki "
               "yaad-dahani set ki hai. Shuru karne ke liye \"HAAN\" likhein."),
        "en": ("Assalam-o-alaikum {name} ji. {caretaker} has set up medicine "
               "reminders for you. Reply \"HAAN\" to begin."),
    },
    "optin_confirmed": {
        "ur": ("Bohot shukriya {name} ji. Ab se hum aap ko har dawai ke waqt yaad "
               "dila denge."),
        "en": ("Thank you {name} ji. From now on we'll remind you at each "
               "medicine time."),
    },
    "stopped": {
        "ur": ("Theek hai {name} ji, ab yaad-dahani band kar di hai. "
               "{caretaker} ko bata diya hai."),
        "en": ("Alright {name} ji, reminders are now stopped. {caretaker} has "
               "been informed."),
    },

    # ------------------------------------------------------------------
    # safety - fixed copy, quoted verbatim from AGENTS.md section 11.
    # DO NOT REWORD. tests/test_guardrails.py asserts against these.
    # ------------------------------------------------------------------
    "refusal_clinical": {
        "ur": ("Main ye faisla nahi kar sakta - ye doctor sahab ka kaam hai. "
               "Main abhi {caretaker} ko bata deta hoon, aur ye baat aap ki agli "
               "report mein bhi likh di jayegi."),
        "en": ("I cannot make that decision - that is the doctor's call. I am "
               "telling {caretaker} now, and it will also be noted in your next "
               "report."),
    },
    "emergency": {
        "ur": ("Ye zaroori lag raha hai. Bara-e-meherbani foran doctor se raabta "
               "karein ya kisi ko bulayein. Main abhi {caretaker} ko ittila de "
               "raha hoon."),
        "en": ("This sounds urgent. Please contact a doctor or call someone "
               "immediately. I am notifying {caretaker} right now."),
    },

    # ------------------------------------------------------------------
    # questions about a medicine (invariant 9)
    # ------------------------------------------------------------------
    "medicine_info": {
        "ur": "{medicine} {purpose}. {food_rule}",
        "en": "{medicine} {purpose}. {food_rule}",
    },
    #: Used when knowledge.get_confirmed() returns None. The agent says it does
    #: not know rather than inventing an answer - this string IS invariant 9 in
    #: its user-facing form.
    "medicine_info_unconfirmed": {
        "ur": ("Is dawai ke baare mein mere paas tasdeeq shuda maloomat nahi "
               "hain, is liye main andaza nahi lagaunga. Main {caretaker} se "
               "pooch leta hoon."),
        "en": ("I don't have confirmed information about this medicine, so I "
               "won't guess. I'll ask {caretaker}."),
    },

    # ------------------------------------------------------------------
    # fallbacks
    # ------------------------------------------------------------------
    #: Confidence below 0.6 - ask ONE short question, never guess (section 11).
    "clarify": {
        "ur": "Maaf kijiye ga, samajh nahi aaya. Kya aap ne {medicine} le li hai?",
        "en": "Sorry, I didn't catch that. Have you taken {medicine}?",
    },
    "clarify_generic": {
        "ur": "Maaf kijiye ga, samajh nahi aaya. Dobara likh dein?",
        "en": "Sorry, I didn't catch that. Could you say it again?",
    },
    "symptom_ack": {
        "ur": ("Allah aap ko sehat de. Main ne ye likh liya hai aur {caretaker} "
               "ko bata diya hai."),
        "en": ("I hope you feel better. I've noted this and told {caretaker}."),
    },
    "unknown_number": {
        "ur": "Maaf kijiye, ye number hamare paas darj nahi hai.",
        "en": "Sorry, this number isn't registered with us.",
    },
}


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Look up a string in the patient's language and fill in its placeholders.

    Falls back to Urdu for an unknown language.

    Raises KeyError on a missing key rather than returning the key itself - a
    missing string is a bug we want to see in development, not something to
    ship silently to a 68-year-old.

    A missing *placeholder* is not fatal: the placeholder is left visibly
    unfilled and logged, because a slightly odd message still beats a crash in
    the middle of a dose reminder.
    """
    if key not in STRINGS:
        raise KeyError(f"no such string: {key!r}")

    variants = STRINGS[key]
    template = variants.get(lang) or variants[DEFAULT_LANGUAGE]

    try:
        return template.format(**kwargs)
    except KeyError as missing:
        log.warning("string %r is missing placeholder %s", key, missing)
        return template.format_map(_Blank(kwargs))


class _Blank(dict):
    """Leaves an unknown placeholder visible instead of raising."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def button(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """A button label, trimmed to Green API's 25-character limit."""
    return t(key, lang)[:25]


def all_keys() -> list[str]:
    return sorted(STRINGS)


def missing_translations() -> list[str]:
    """Keys that do not exist in every supported language.

    Invariant 12 says both languages exist from the start; this is how a gap
    gets caught in a test rather than in front of a patient.
    """
    return [k for k, v in STRINGS.items()
            if any(lang not in v or not v[lang] for lang in LANGUAGES)]
