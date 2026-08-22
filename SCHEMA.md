# MedNuskha — Database schema

**Locked at the end of Phase 0.** Source of truth is
[`backend/app/models.py`](backend/app/models.py); this file is the human-readable
mirror. Changing a column means changing both, and logging the reason in
`PROJECT_LOG.md`.

Eleven tables, per AGENTS.md §8.

## Conventions

| Rule | Detail |
|---|---|
| Primary keys | UUID4 **strings**, matching the `str` ids in the §9 contracts |
| Timestamps | `timestamptz`, always stored **UTC**; converted to `Asia/Karachi` at the edge |
| Dates | plain `date`, always Asia/Karachi calendar days |
| Enums | plain `text` columns. Allowed values are module constants in `models.py`, not Postgres enums — we have no migrations tooling (§4) and text survives a schema tweak |
| Phone numbers | digits only, no `+`, no leading zero: `923001234567` (§10) |
| JSON | `JSONB` |
| Migrations | none. `SQLModel.metadata.create_all` at startup **creates missing tables only** — it never alters an existing one. A column change during the build means dropping that table by hand |

---

## 1. `family`

A household. Caretakers and patients both hang off one family — that is how
multiple caretakers link to one patient (§4.10) without a join table.

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | uuid4 |
| `name` | text | |
| `created_at` | timestamptz | default now (UTC) |

## 2. `caretaker`

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `family_id` | text FK → `family.id` | indexed |
| `name` | text | |
| `phone` | text | **UNIQUE**, indexed. Digits only |
| `relation` | text | free text: `son`, `daughter`, `spouse`, `caregiver`. Used in message copy — "aap ke bete ne…" — and shown across the dashboard (§8) |
| `language` | text | `ur` \| `en`, default `ur` |
| `otp_code` | text NULL | phone + OTP signup (§4.1); a dev bypass is acceptable |
| `otp_expires_at` | timestamptz NULL | |
| `verified` | bool | default `false` |
| `created_at` | timestamptz | |

## 3. `patient`

The elderly person receiving reminders. Never logs in anywhere (§3.1).

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `family_id` | text FK → `family.id` | indexed |
| `name` | text | |
| `whatsapp_number` | text | **UNIQUE**, indexed. Digits only |
| `language` | text | `ur` \| `en`, default `ur` |
| `opted_in` | bool | default `false`. Set true only after the patient replies HAAN to `patient_optin` (§4.4). **No reminder is sent to a patient who has not opted in** |
| `opted_in_at` | timestamptz NULL | |
| `stopped` | bool | default `false`. Patient sent STOP — everything outbound halts and the caretaker is told |
| `created_at` | timestamptz | |

## 4. `medicine_reference`

The cache of AI-fetched, caretaker-confirmed medicine knowledge (§8, invariant 9).
One row per unique medicine name **across the whole system** — fetched once,
reused by every patient later prescribed the same medicine.

A row is created by `agent.knowledge.fetch_draft` as a **draft**
(`confirmed = false`). It is never surfaced to a patient and never usable by the
agent until a caretaker confirms it on the dashboard.

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `canonical_name` | text | **UNIQUE**, indexed |
| `aliases` | jsonb NULL | list of strings |
| `purpose_ur` | text NULL | simple Urdu |
| `purpose_en` | text NULL | |
| `food_rule` | text NULL | e.g. "khane ke baad" |
| `common_timing` | text NULL | e.g. "subah aur raat" |
| `source` | text | `ai_fetched` \| `caretaker_edited` |
| `confirmed` | bool | default `false`, indexed. **The agent may only ever read `true` rows** |
| `confirmed_by` | text FK → `caretaker.id` NULL | |
| `fetched_at` | timestamptz | |
| `confirmed_at` | timestamptz NULL | |

## 5. `medicine`

One medicine prescribed to one patient. A patient may have several active at
once, each with its own schedule and its own independent tenure (§4.3).

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `patient_id` | text FK → `patient.id` | indexed |
| `reference_id` | text FK → `medicine_reference.id` NULL | the shared confirmed-knowledge row |
| `name` | text | as prescribed |
| `strength` | text NULL | e.g. `500mg`. Included in patient-facing copy every time (§11) |
| `form` | text NULL | tablet / syrup / capsule |
| `notes` | text NULL | |
| `active` | bool | default `true`, indexed |
| `created_at` | timestamptz | |

## 6. `schedule`

One row per medicine's course (§8).

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `medicine_id` | text FK → `medicine.id` | indexed |
| `dose_times` | jsonb NOT NULL | local Asia/Karachi wall-clock `"HH:MM"` strings, e.g. `["08:00","20:00"]` |
| `duration_days` | int | the tenure the caretaker picked: 7 / 14 / 30 / custom (§4.3) |
| `start_date` | date | |
| `end_date` | date | indexed. **INCLUSIVE — the last day a dose is due** |
| `active` | bool | default `true`, indexed |
| `created_at` | timestamptz | |

> **`end_date` is inclusive.** A 7-day course starting 2026-08-22 has
> `end_date = 2026-08-28`, and `duration_days × len(dose_times)` doses total.
> AGENTS.md §8 writes the formula as `start_date + duration_days`, which would
> produce an 8th day of doses. Inclusive is what "a 7-day course" means to a
> caretaker and what reads correctly on the doctor PDF. Logged in
> PROJECT_LOG.md, Session 1.
>
> Course-end check (Phase 6): `end_date < today`.

## 7. `dose_event`

One scheduled dose and everything that happened to it.
**`state` is mutated only by `scheduler/state_machine.py`** (§8).

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | this is the id that travels in the button payload (invariant 2) |
| `schedule_id` | text FK → `schedule.id` | indexed |
| `patient_id` | text FK → `patient.id` | indexed. Denormalised so the dashboard's 5-second poll is a single-table query |
| `idempotency_key` | text | **UNIQUE** (`uq_dose_event_idempotency_key`). Format `"{schedule_id}:{scheduled_at ISO-8601 UTC}"` |
| `scheduled_at` | timestamptz | indexed. When the dose is due, UTC |
| `state` | text | indexed. One of the eight states below |
| `sent_at` | timestamptz NULL | |
| `followup_sent_at` | timestamptz NULL | |
| `responded_at` | timestamptz NULL | |
| `caretaker_alerted_at` | timestamptz NULL | |
| `response_source` | text NULL | `button` \| `text` \| `voice` |
| `response_text` | text NULL | the patient's own words — quoted verbatim in the doctor report |
| `reason` | text NULL | stated reason for not taking |
| `voice_note_key` | text NULL | Supabase Storage key of the pre-generated Urdu voice note (Phase 5) |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Extra indexes: `(patient_id, scheduled_at)`, `(state, scheduled_at)`.

**States** — `SCHEDULED → SENT → AWAITING_REPLY → REMINDED_AGAIN → {TAKEN | TAKEN_LATE | MISSED | SKIPPED}`

Terminal states (`TAKEN`, `TAKEN_LATE`, `MISSED`, `SKIPPED`) end the escalation
chain. `MISSED` is the one terminal state that can still move — a late
confirmation reclassifies it to `TAKEN_LATE` (§4.8).

The UNIQUE `idempotency_key` is what satisfies invariant 5: materialisation is
safe to re-run every minute and a restart never sends a second reminder.

## 8. `message_log`

Every inbound and outbound WhatsApp message.

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `wa_message_id` | text NULL | **UNIQUE** (`uq_message_log_wa_message_id`), indexed. This is the §5.4 deduplication mechanism |
| `direction` | text | `in` \| `out`, indexed |
| `kind` | text | `text` \| `template` \| `button` \| `interactive` \| `audio` \| `image` \| `other` |
| `patient_id` | text FK NULL | indexed |
| `caretaker_id` | text FK NULL | indexed |
| `dose_event_id` | text FK NULL | indexed |
| `from_number` / `to_number` | text NULL | |
| `body` | text NULL | |
| `payload` | text NULL | button payload, e.g. `TAKEN:<dose_id>` |
| `media_id` | text NULL | |
| `template_name` | text NULL | |
| `status` | text NULL | sent / delivered / read / failed |
| `error` | text NULL | |
| `raw` | jsonb NULL | untouched Meta payload, for debugging at 11pm (§12) |
| `created_at` | timestamptz | |

> `wa_message_id` is nullable because an outbound send that fails never receives
> an id from Meta, and Postgres permits many NULLs under a unique index. A
> rejected insert on a duplicate is **correct behaviour, not a bug** (§17).

## 9. `symptom_report`

Recorded verbatim and never interpreted by the agent (invariant 8) — quoted
as-is in the doctor report (§6).

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `patient_id` | text FK → `patient.id` | indexed |
| `dose_event_id` | text FK NULL | |
| `text_verbatim` | text | |
| `language` | text | default `ur` |
| `severity` | text | `routine` \| `emergency` |
| `caretaker_alerted` | bool | default `false` |
| `reported_at` | timestamptz | |

## 10. `prescription`

Phase 7, stretch.

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `patient_id` | text FK → `patient.id` | indexed |
| `uploaded_by` | text FK → `caretaker.id` NULL | |
| `storage_key` | text NULL | |
| `raw_extraction` | jsonb NULL | raw Qwen-VL response, stored **before** parsing so a bad extraction is debuggable rather than lost |
| `confirmation_state` | text | `pending` \| `confirmed` \| `discarded`, default `pending` |
| `confirmed_by` | text FK → `caretaker.id` NULL | |
| `confirmed_at` | timestamptz NULL | |
| `created_at` | timestamptz | |

> Nothing is scheduled from a prescription until `confirmation_state = confirmed`
> — invariant 3, no exceptions for the demo.

## 11. `report`

One generated PDF (§8, Phase 6).

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | |
| `patient_id` | text FK → `patient.id` | indexed |
| `medicine_id` | text FK → `medicine.id` NULL | indexed. **NULL means "whole patient"** rather than one course |
| `kind` | text | `doctor` \| `caretaker` |
| `trigger` | text | `course_end` \| `on_demand`, default `on_demand` |
| `period_start` | date | |
| `period_end` | date | |
| `storage_key` | text | Supabase Storage key |
| `generated_at` | timestamptz | |

Course-end dedupe key (Phase 6): `(medicine_id, kind, trigger = 'course_end')`.

---

## Relationship map

```
family ─┬─< caretaker
        └─< patient ─┬─< medicine ──< schedule ──< dose_event
                     ├─< symptom_report
                     ├─< prescription
                     └─< report

medicine_reference ──< medicine      (shared across all patients)
message_log ── patient / caretaker / dose_event   (all nullable)
```

## Unique constraints, in one place

| Table | Constraint | Why |
|---|---|---|
| `dose_event` | `idempotency_key` | invariant 5 — a restart never re-sends |
| `message_log` | `wa_message_id` | invariant 4 — inbound deduplication |
| `caretaker` | `phone` | one account per number |
| `patient` | `whatsapp_number` | one patient per number |
| `medicine_reference` | `canonical_name` | one knowledge row per medicine, system-wide |
