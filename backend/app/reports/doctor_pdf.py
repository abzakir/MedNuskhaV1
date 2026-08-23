"""One-page clinical PDF for the doctor. Phase 6.

Contents: patient name, medicine name and tenure (start date, duration, end
date), adherence percentage for that medicine's course, timing distribution
(on time / late / missed), missed-dose log with the patient's stated reason
quoted verbatim, symptoms reported verbatim.

Invariant 11: nothing here claims the patient was observed taking a dose. The
report carries an explicit line stating these are patient-reported
confirmations, not observed ingestion - and the word "reported" is used
throughout rather than "taken", for the same reason.

Tone: clinical and neutral. A doctor reads this in under a minute between
patients, so every number is above the fold and nothing is editorialised.
"""

from __future__ import annotations

from app.reports import data, pdf
from app.reports.data import CourseReport

_PHASE = "Phase 6 - reports"

ACCENT = (23, 74, 110)

#: The line invariant 11 exists for. It is a callout, not a footnote, because
#: a doctor changing a prescription on the strength of this must see it.
DISCLAIMER = (
    "These are patient-reported confirmations collected over WhatsApp, not "
    "observed ingestion. A dose recorded as taken means the patient replied "
    "that they had taken it. Doses still awaiting a reply are excluded from "
    "the adherence figure rather than counted as missed."
)


def _adherence_label(report: CourseReport) -> tuple[str, tuple[int, int, int]]:
    percent = report.percent
    if percent is None:
        return "n/a", pdf.MUTED
    if percent >= 80:
        return f"{percent}%", pdf.GOOD
    if percent >= 50:
        return f"{percent}%", pdf.WARN
    return f"{percent}%", pdf.BAD


def _render(report: CourseReport) -> bytes:
    doc = pdf.Report(
        accent=ACCENT,
        footer_note=f"MedNuskha - {report.patient_name} - "
                    f"{report.medicine_label} - patient-reported data",
    )

    doc.title_block(
        title="Medication Adherence Report",
        subtitle=f"{report.patient_name}  -  {report.medicine_label}",
        right=f"Generated {report.generated_at:%d %b %Y %H:%M}",
    )

    percent, colour = _adherence_label(report)

    doc.facts(
        [("Course", f"{report.start_date:%d %b} to {report.end_date:%d %b %Y}"),
         ("Duration", f"{report.duration_days} days"),
         ("Doses scheduled", str(report.scheduled)),
         ("Adherence", percent)],
        widths=[0.37, 0.19, 0.24, 0.20],
    )

    # The headline number again, in words, so it cannot be misread from the
    # tile alone - "86%" of what is the question a doctor asks next.
    if report.percent is None:
        summary = ("No dose in this course has a settled outcome yet, so no "
                   "adherence figure can be given.")
    else:
        summary = (f"{report.taken} of {report.decided} settled doses were "
                   f"reported taken.")
        if report.pending:
            summary += f" {report.pending} still awaiting a reply."
    doc.body(summary, size=9.5, colour=colour, gap=3)

    # -- timing ----------------------------------------------------------

    doc.heading("Timing distribution")
    doc.table(
        headers=["Outcome", "Doses", "Share of settled"],
        rows=[
            ["Reported taken, on time", str(report.on_time),
             _share(report.on_time, report.decided)],
            ["Reported taken, late", str(report.late),
             _share(report.late, report.decided)],
            ["Missed - no confirmation", str(report.missed),
             _share(report.missed, report.decided)],
            ["Declined by patient", str(report.skipped),
             _share(report.skipped, report.decided)],
        ],
        widths=[0.52, 0.18, 0.30],
        aligns="LRR",
    )

    if len(report.by_time) > 1:
        doc.heading("By scheduled dose time")
        doc.table(
            headers=["Dose time", "Reported taken", "Not taken", "Adherence"],
            rows=[[t.hhmm, str(t.taken), str(t.missed),
                   f"{t.percent}%" if t.percent is not None else "n/a"]
                  for t in report.by_time],
            widths=[0.28, 0.26, 0.22, 0.24],
            aligns="LRRR",
        )

    # -- missed doses ----------------------------------------------------

    doc.heading("Missed doses and stated reasons")
    if not report.missed_log:
        doc.body("No dose in this course went unconfirmed.", size=9.5)
    else:
        doc.body("Reasons are the patient's own words, unedited and "
                 "untranslated.", size=8.5, colour=pdf.MUTED, gap=2.5)
        for entry in report.missed_log:
            when = f"{entry.when:%a %d %b, %H:%M}" if entry.when else "unknown time"
            state = "declined" if entry.state == "SKIPPED" else "no confirmation"
            if entry.said:
                doc.quote(entry.said, f"{when}  -  {state}")
            else:
                doc.body(f"{when}  -  {state}, no reason given",
                         size=9.5, gap=2.5, colour=pdf.MUTED,
                         indent=doc.QUOTE_INDENT)

    # -- symptoms --------------------------------------------------------

    doc.heading("Symptoms reported during this course")
    if not report.symptoms:
        doc.body("None reported.", size=9.5)
    else:
        doc.body("Recorded verbatim. The system does not interpret, triage or "
                 "diagnose these.", size=8.5, colour=pdf.MUTED, gap=2.5)
        for symptom in report.symptoms:
            when = f"{symptom.when:%a %d %b, %H:%M}" if symptom.when else ""
            urgent = symptom.severity == "emergency"
            doc.quote(
                symptom.text,
                f"{when}  -  FLAGGED URGENT, caretaker alerted" if urgent else when,
                attribution_colour=pdf.BAD if urgent else None,
                bar_colour=pdf.BAD if urgent else None,
            )

    doc.ln(1)
    doc.callout(DISCLAIMER, colour=pdf.MUTED)

    return doc.render()


def _share(count: int, total: int) -> str:
    return f"{round(count / total * 100)}%" if total else "-"


def build(patient_id: str, medicine_id: str | None = None) -> bytes:
    """Render the doctor report to PDF bytes.

    `medicine_id` None means the patient's most recent medicine - the report
    describes one course, because tenure and adherence are per-medicine
    (section 4.3).
    """
    if medicine_id is None:
        medicine_id = data.latest_medicine_id(patient_id)
        if medicine_id is None:
            raise LookupError(f"patient {patient_id} has no medicine to report on")

    return _render(data.for_course(patient_id, medicine_id))
