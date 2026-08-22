"""One-page clinical PDF for the doctor, via WeasyPrint. Phase 6.

Contents: patient name, medicine name and tenure (start date, duration, end
date), adherence percentage for that medicine's course, timing distribution
(on time / late / missed), missed-dose log with the patient's stated reason
quoted verbatim, symptoms reported verbatim.

Invariant 11: nothing claims the patient was observed taking a dose. The
report carries an explicit line stating these are patient-reported
confirmations, not observed ingestion.
"""

from __future__ import annotations

_PHASE = "Phase 6 - reports"


def build(patient_id: str, medicine_id: str | None = None) -> bytes:
    """Render the doctor report to PDF bytes.

    `medicine_id` None means the whole patient rather than one course.
    """
    raise NotImplementedError(_PHASE)
