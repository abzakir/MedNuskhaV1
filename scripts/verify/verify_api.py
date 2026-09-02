"""Phase 4 backend verification: the REST API the dashboard runs on."""
import os
import sys
from pathlib import Path

# scripts/verify/<this file> -> scripts/verify -> scripts -> <repo root>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

from fastapi.testclient import TestClient
from sqlmodel import select

from app.config import settings
settings.dev_auth_bypass = True

from app.db import session_scope
from app.main import app
from app.models import (Caretaker, DoseEvent, Family, Medicine,
                        MedicineReference, MessageLog, Patient, Schedule,
                        SymptomReport)

OK, BAD = [], []
NUM = "923007770001"
MED = "cetirizine"


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


def cleanup():
    with session_scope() as s:
        for p in s.exec(select(Patient).where(Patient.whatsapp_number == NUM)).all():
            for t in (MessageLog, SymptomReport):
                for r in s.exec(select(t).where(t.patient_id == p.id)).all():
                    s.delete(r)
            s.commit()
            for m in s.exec(select(Medicine).where(Medicine.patient_id == p.id)).all():
                for sc in s.exec(select(Schedule).where(
                        Schedule.medicine_id == m.id)).all():
                    for d in s.exec(select(DoseEvent).where(
                            DoseEvent.schedule_id == sc.id)).all():
                        s.delete(d)
                    s.commit(); s.delete(sc)
                s.commit(); s.delete(m)
            s.commit()
            for d in s.exec(select(DoseEvent).where(
                    DoseEvent.patient_id == p.id)).all():
                s.delete(d)
            s.commit(); s.delete(p)
        s.commit()
        # medicine.reference_id points here, so references go LAST.
        for r in s.exec(select(MedicineReference).where(
                MedicineReference.canonical_name == MED)).all():
            s.delete(r)
        s.commit()


cleanup()

# The dev caretaker persists between runs, so clear the phone it set last time
# or the "needs_phone" assertion tests stale state instead of the code.
with session_scope() as s_:
    for row in s_.exec(select(Caretaker).where(
            Caretaker.auth_user_id == "dev-bypass-user")).all():
        row.phone = None
        s_.add(row)
    s_.commit()

c = TestClient(app)

print("=== A. auth")
r = c.get("/api/me")
check("dev bypass signs us in", r.status_code == 200, r.status_code)
me = r.json()
check("a family was created on first sign-in", me["family"]["id"], me)
check("dashboard is told the phone is missing", me["needs_phone"] is True, me)

settings.dev_auth_bypass = False
check("without a token and without the bypass -> 401",
      c.get("/api/me").status_code == 401)
check("a garbage token is rejected",
      c.get("/api/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401)
settings.dev_auth_bypass = True

print("\n=== B. caretaker profile")
r = c.patch("/api/me", json={"name": "Zakir", "phone": "0300 777 0002",
                             "relation": "beta"})
check("profile saved", r.status_code == 200, r.text[:120])
check("phone normalised to 923007770002",
      r.json()["phone"] == "923007770002", r.json().get("phone"))
check("needs_phone now false", r.json()["needs_phone"] is False)

print("\n=== C. add a patient")
r = c.post("/api/patients", json={"name": "Ammi", "whatsapp_number": "+92 300 777-0001",
                                  "language": "ur", "relation": "beta"})
check("patient created", r.status_code == 201, r.text[:150])
patient_id = r.json()["id"]
check("number normalised", r.json()["whatsapp_number"] == NUM, r.json())

r = c.post("/api/patients", json={"name": "Dup", "whatsapp_number": NUM})
check("duplicate number rejected with 409", r.status_code == 409, r.status_code)

r = c.post("/api/patients", json={"name": "Bad", "whatsapp_number": "123"})
check("nonsense number rejected with 422", r.status_code == 422, r.status_code)

print("\n=== D. medicine lookup produces a DRAFT, never live data")
r = c.post("/api/medicines/lookup", json={"name": MED})
check("lookup succeeded", r.status_code == 200, r.text[:150])
draft = r.json()
print(f"     purpose_ur: {draft.get('purpose_ur')}")
print(f"     food_rule : {draft.get('food_rule')}")
check("draft is NOT confirmed (invariant 9)", draft.get("confirmed") is False, draft)
with session_scope() as s:
    row = s.exec(select(MedicineReference).where(
        MedicineReference.canonical_name == MED)).first()
check("looking up alone writes NOTHING to the database", row is None,
      "a row was created before the caretaker confirmed")

print("\n=== E. the agent cannot use an unconfirmed draft")
from app.agent import knowledge
check("get_confirmed still returns None", knowledge.get_confirmed(MED) is None)

print("\n=== F. confirm & add - the only path that activates anything")
r = c.post("/api/medicines", json={
    "patient_id": patient_id, "name": MED, "strength": "10mg",
    "dose_times": ["21:00", "9:00"], "duration_days": 7,
    "purpose_ur": "allergy aur chheenk ke liye",
    "purpose_en": "for allergy and sneezing",
    "food_rule": "Khane ke baad lein.", "edited": True})
check("medicine added", r.status_code == 201, r.text[:200])
sched = r.json()["schedule"]
check("dose times sorted and zero-padded",
      sched["dose_times"] == ["09:00", "21:00"], sched["dose_times"])
from datetime import date, timedelta
check("end_date is INCLUSIVE - 7 days spans 7 calendar days",
      date.fromisoformat(sched["end_date"]) ==
      date.fromisoformat(sched["start_date"]) + timedelta(days=6), sched)

info = knowledge.get_confirmed(MED)
check("NOW the agent can use it", info is not None and info.confirmed)
check("and it holds the caretaker's edited words",
      info and "allergy aur chheenk" in (info.purpose_ur or ""), info)
with session_scope() as s:
    row = s.exec(select(MedicineReference).where(
        MedicineReference.canonical_name == MED)).first()
    check("marked as caretaker-edited, not AI",
          row.source == "caretaker_edited", row.source)
    check("records WHICH human signed it off", bool(row.confirmed_by), row.confirmed_by)

print("\n=== G. doses appear immediately, no waiting for a tick")
r = c.get(f"/api/patients/{patient_id}/today")
check("today endpoint works", r.status_code == 200, r.text[:120])
today = r.json()
check("doses materialised on save", today["summary"]["total"] >= 1, today["summary"])
if today["doses"]:
    d = today["doses"][0]
    check("dose names the medicine and strength",
          "cetirizine" in d["medicine"].lower() and "10mg" in d["medicine"], d)
    check("time shown in local HH:MM", ":" in d["time"], d)

print("\n=== H. patient detail")
r = c.get(f"/api/patients/{patient_id}")
check("patient detail works", r.status_code == 200, r.text[:120])
detail = r.json()
check("one medicine listed", len(detail["medicines"]) == 1, len(detail["medicines"]))
m = detail["medicines"][0]
check("days remaining shown", m["schedule"]["days_remaining"] == 7,
      m["schedule"]["days_remaining"])
check("confirmed info attached", m["info"]["confirmed"] is True, m["info"])
check("per-medicine adherence present", "percent" in m["adherence"], m["adherence"])

print("\n=== I. family overview")
r = c.get("/api/patients")
check("overview works", r.status_code == 200, r.text[:120])
row = [p for p in r.json() if p["id"] == patient_id][0]
check("shows medicine count", row["medicine_count"] == 1, row)
check("shows today's totals", row["today"]["total"] >= 1, row["today"])

print("\n=== J. event log")
r = c.get(f"/api/patients/{patient_id}/events")
check("event log works", r.status_code == 200, r.text[:120])

print("\n=== K. a caretaker cannot see another family's patient")
with session_scope() as s:
    other_fam = Family(name="SOMEONE ELSE"); s.add(other_fam); s.commit(); s.refresh(other_fam)
    other = Patient(family_id=other_fam.id, name="Not Yours",
                    whatsapp_number="923009998888")
    s.add(other); s.commit(); s.refresh(other)
    other_id, other_fam_id = other.id, other_fam.id

for path in (f"/api/patients/{other_id}", f"/api/patients/{other_id}/today",
             f"/api/patients/{other_id}/events"):
    check(f"{path.split('/')[-1] or 'detail'} -> 404 for another family",
          c.get(path).status_code == 404, c.get(path).status_code)

r = c.post("/api/medicines", json={"patient_id": other_id, "name": "x",
                                   "dose_times": ["08:00"], "duration_days": 3})
check("cannot add a medicine to another family's patient",
      r.status_code == 404, r.status_code)

print("\n=== L. stopping a medicine keeps the history")
med_id = detail["medicines"][0]["id"]
r = c.delete(f"/api/medicines/{med_id}")
check("stop works", r.status_code == 200, r.text[:120])
r = c.get(f"/api/patients/{patient_id}")
check("medicine still listed, marked inactive",
      r.json()["medicines"] and r.json()["medicines"][0]["active"] is False,
      r.json()["medicines"])

with session_scope() as s:
    o = s.get(Patient, other_id)
    if o: s.delete(o)
    s.commit()
    f = s.get(Family, other_fam_id)
    if f: s.delete(f)
    s.commit()
cleanup()

print(f"\n{'=' * 60}\n  {len(OK)} passed, {len(BAD)} failed")
for f in BAD:
    print(f"    FAILED: {f}")
sys.exit(1 if BAD else 0)
