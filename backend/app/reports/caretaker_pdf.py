"""One-page plain-language PDF for the caretaker. Phase 6.

The doctor report and this one describe the same course from `data.py`, so
they can never disagree. Everything else about them is different.

This one is written for the son or daughter who set the reminders up. It says
how it went in sentences, celebrates what went well, and is gentle about what
did not. Section 14: "a caring update, not a spreadsheet". So:

- No percentages, no tables, no clinical vocabulary. "11 of 14" is a fact a
  person can hold; "78.6% adherence" is a metric about their mother.
- Never scolds, and never implies the caretaker or the patient failed. A
  missed dose is information, not an accusation (section 11).
- It does not advise. Anything that reads as a next step points at the doctor,
  because this file is not allowed to practise medicine either (invariant 8).

Copy lives here rather than in i18n/strings.py: that module is every
patient-facing WhatsApp string, and these are paragraphs of a document that
have to be read as a whole to be reviewed.
"""

from __future__ import annotations

from app.reports import data, pdf
from app.reports.data import CourseReport

ACCENT = (21, 101, 84)

#: Roman Urdu, matching how the caretaker is addressed on WhatsApp - the
#: strings in i18n/strings.py are Roman Urdu too, not Urdu script.
COPY: dict[str, dict[str, str]] = {
    "en": {
        "title": "How it went",
        "subtitle": "{patient} and {medicine}",
        "generated": "Generated {when}",
        "period": "{start} to {end}",
        "headline_none": "This course has not started properly yet, so there "
                         "is nothing to report on so far.",
        "headline": "{patient} took {taken} of the {total} doses in this "
                    "course.",
        "still_open": "{n} more are still to be answered.",
        "praise_all": "Every single dose was confirmed. That is genuinely "
                      "hard to do over {days} days.",
        "praise_most": "That is most of them - worth saying well done to "
                       "{patient}.",
        "praise_streak": "The longest run without a gap was {n} doses.",
        "praise_current": "The last {n} doses in a row were all confirmed.",
        "hardest_head": "The time of day that was hardest",
        "hardest": "The {time} dose was the one most often missed - {n} times "
                   "across the course. If that time is awkward, it is worth "
                   "asking the doctor whether it can move.",
        "hardest_none": "No particular time of day was harder than another.",
        "missed_head": "What was missed",
        "missed_none": "Nothing was missed. There is nothing to follow up.",
        "missed_intro": "These are the doses that were not confirmed, with "
                        "what {patient} said at the time, in their own words.",
        "no_reason": "No reason given.",
        "symptoms_head": "Things {patient} mentioned",
        "symptoms_intro": "Written down exactly as they were said. Nothing "
                          "here has been interpreted - please pass anything "
                          "that worries you to the doctor.",
        "alerted": "you were alerted about this at the time",
        "close": "This is a record of what {patient} told us over WhatsApp. It "
                 "is not a medical assessment, and it is not a substitute for "
                 "the doctor. If anything here concerns you, take the other "
                 "copy of this report - the clinical one - to their next "
                 "appointment.",
    },
    "ur": {
        "title": "Kaisa raha",
        "subtitle": "{patient} aur {medicine}",
        "generated": "{when}",
        "period": "{start} se {end} tak",
        "headline_none": "Ye course abhi theek se shuru nahi hua, is liye "
                         "abhi batane ko kuch khaas nahi hai.",
        "headline": "{patient} ne is course ki {total} mein se {taken} "
                    "khurakein li hain.",
        "still_open": "{n} ka jawab abhi aana baqi hai.",
        "praise_all": "Ek bhi khurak nahi chhooti. {days} din tak ye karna "
                      "waqai aasan nahi hota.",
        "praise_most": "Ye zyada tar hain - {patient} ko bata dijiye ga.",
        "praise_streak": "Sab se lamba silsila {n} khurakon ka raha, bina "
                         "kisi naghe ke.",
        "praise_current": "Aakhri {n} khurakein musalsal li gayi hain.",
        "hardest_head": "Din ka sab se mushkil waqt",
        "hardest": "{time} wali khurak sab se zyada chhooti - poore course "
                   "mein {n} baar. Agar ye waqt mushkil hai to doctor se "
                   "poochh lijiye ke kya ise badla ja sakta hai.",
        "hardest_none": "Din ka koi ek waqt dusre se zyada mushkil nahi raha.",
        "missed_head": "Kya chhoot gaya",
        "missed_none": "Kuch nahi chhoota. Follow up karne ki zaroorat nahi.",
        "missed_intro": "Ye wo khurakein hain jin ki tasdeeq nahi hui, aur "
                        "sath mein {patient} ne us waqt jo kaha - unhi ke "
                        "alfaz mein.",
        "no_reason": "Koi wajah nahi batai gayi.",
        "symptoms_head": "{patient} ne jo baatein batayin",
        "symptoms_intro": "Bilkul waise hi likhi gayi hain jaise kahi gayin. "
                          "In ka koi matlab nahi nikala gaya - jo baat aap ko "
                          "pareshan kare, wo doctor tak zaroor pahunchayein.",
        "alerted": "us waqt aap ko ittila kar di gayi thi",
        "close": "Ye us baat ka record hai jo {patient} ne WhatsApp par "
                 "batayi. Ye tibbi raye nahi hai aur doctor ka mutabadil nahi "
                 "hai. Agar yahan koi baat aap ko pareshan kare to is report "
                 "ki dusri copy - doctor wali - agli appointment par sath le "
                 "jayein.",
    },
}


def _t(lang: str) -> dict[str, str]:
    return COPY.get(lang) or COPY["en"]


def _render(report: CourseReport, lang: str) -> bytes:
    c = _t(lang)
    name = report.patient_name

    doc = pdf.Report(
        accent=ACCENT,
        footer_note=f"MedNuskha  -  {name}  -  {report.medicine_label}",
    )

    doc.title_block(
        title=c["title"],
        subtitle=c["subtitle"].format(patient=name,
                                      medicine=report.medicine_label),
        right=c["generated"].format(
            when=f"{report.generated_at:%d %b %Y}"),
    )

    doc.body(c["period"].format(start=f"{report.start_date:%d %b %Y}",
                                end=f"{report.end_date:%d %b %Y}"),
             size=9, colour=pdf.MUTED, gap=4)

    # -- the one number that matters, in a sentence ----------------------

    if report.decided == 0:
        doc.body(c["headline_none"], size=13, gap=3)
    else:
        doc.body(c["headline"].format(patient=name, taken=report.taken,
                                      total=report.decided),
                 size=13, gap=1.5)

        extras: list[str] = []
        if report.pending:
            extras.append(c["still_open"].format(n=report.pending))
        if report.missed == 0 and report.skipped == 0 and report.taken:
            extras.append(c["praise_all"].format(days=report.duration_days))
        elif report.percent is not None and report.percent >= 70:
            extras.append(c["praise_most"].format(patient=name))
        if report.best_streak >= 3:
            if report.current_streak >= 3 and report.current_streak == report.best_streak:
                extras.append(c["praise_current"].format(n=report.current_streak))
            else:
                extras.append(c["praise_streak"].format(n=report.best_streak))

        if extras:
            doc.body(" ".join(extras), size=10.5, gap=3)

    # -- hardest time of day ---------------------------------------------

    hardest = report.hardest_time
    if len(report.by_time) > 1:
        doc.heading(c["hardest_head"])
        if hardest is None:
            doc.body(c["hardest_none"], size=10.5)
        else:
            doc.body(c["hardest"].format(time=hardest.hhmm, n=hardest.missed),
                     size=10.5)

    # -- what was missed --------------------------------------------------

    doc.heading(c["missed_head"])
    if not report.missed_log:
        doc.body(c["missed_none"], size=10.5)
    else:
        doc.body(c["missed_intro"].format(patient=name),
                 size=9, colour=pdf.MUTED, gap=2.5)
        for entry in report.missed_log:
            when = f"{entry.when:%a %d %b, %H:%M}" if entry.when else ""
            if entry.said:
                doc.quote(entry.said, when)
            else:
                doc.body(f"{when}  -  {c['no_reason']}", size=10, gap=2.5,
                         colour=pdf.MUTED, indent=doc.QUOTE_INDENT)

    # -- symptoms ---------------------------------------------------------

    if report.symptoms:
        doc.heading(c["symptoms_head"].format(patient=name))
        doc.body(c["symptoms_intro"], size=9, colour=pdf.MUTED, gap=2.5)
        for symptom in report.symptoms:
            when = f"{symptom.when:%a %d %b, %H:%M}" if symptom.when else ""
            urgent = symptom.severity == "emergency"
            doc.quote(
                symptom.text,
                f"{when}  -  {c['alerted']}" if urgent else when,
                attribution_colour=pdf.BAD if urgent else None,
                bar_colour=pdf.BAD if urgent else None,
            )

    doc.ln(1)
    doc.callout(c["close"].format(patient=name), colour=pdf.MUTED)

    return doc.render()


def build(patient_id: str, medicine_id: str | None = None,
          lang: str = "en") -> bytes:
    """Render the caretaker report to PDF bytes.

    `lang` is the caretaker's own language, so the same course reads in
    whichever of the two they were addressed in on WhatsApp.
    """
    if medicine_id is None:
        medicine_id = data.latest_medicine_id(patient_id)
        if medicine_id is None:
            raise LookupError(f"patient {patient_id} has no medicine to report on")

    return _render(data.for_course(patient_id, medicine_id), lang)
