# MedNuskha — Agent instructions

> Single source of truth for this repo. Every Claude Code session reads this file
> first, then `PROJECT_LOG.md`, then acts. If a request contradicts this file,
> stop and ask instead of guessing.
>
> **Team:** Runtime Terrors · **Event:** Alibaba Cloud AI Hackathon 2026 (Bano
> Qabil / Alkhidmat Foundation Pakistan) · **Timeline:** 4 days · **Setup:** one
> Claude Code seat, humans take turns driving it, no parallel tracks.
>
> Earlier notes may say "Pehar" — same project, current name is **MedNuskha**.

---

## 0. THE MASTER PROMPT — paste at the start of every Claude Code session

> Read `AGENTS.md` in full, then `PROJECT_LOG.md` in full. Look at "Current
> state", "Current phase" and "Next steps" — that is where the last session
> left off. Tell me in one line what phase we're on and what you're about to
> do, then wait for me to say go.
>
> Rules for this and every session:
> - Do only what the current phase asks. Do not start the next phase.
> - Update `PROJECT_LOG.md` the moment you make any non-trivial decision
>   (schema, library, contract, naming, workaround). Do not batch it — context
>   can run out mid-task.
> - **If you sense context or credits running low, stop immediately, finish
>   the file you're in so nothing is half-written, and update
>   `PROJECT_LOG.md` so the next session resumes with zero memory:** what
>   changed this session, what runs right now, the next concrete step, and any
>   gotcha you discovered. Then tell me you're stopping and why.
> - No placeholder code, no `# TODO: implement`, no functions that `pass`. If
>   you can't finish something, say so and leave the last working state.
> - When unsure about an external API's shape, fetch the docs — do not recall.
> - Stay inside the file layout in §7. Do not add dependencies not in §6.
> - Never commit secrets. `.env` is gitignored; names only in `.env.example`.

Every phase prompt in §14 assumes this one has already been given.

---

## 1. Session protocol

Claude Code sessions do not remember each other, and you *will* hit context or
credit limits during a 4-day build. `PROJECT_LOG.md` is the only bridge between
sessions. Treating it well is the difference between four days of progress and
four days of re-discovery.

**At the start of every session:**
1. Read `AGENTS.md` in full.
2. Read `PROJECT_LOG.md` in full.
3. If `PROJECT_LOG.md` doesn't exist, create it from the template in §16.

**During the session, log immediately when any of these happen:**
- A non-trivial decision (schema, library, API contract, naming, architecture).
- A workaround or discovery that took more than a couple of minutes.
- A blocker, and how (or whether) it was resolved.
- A reversal of an earlier decision, with the reason.

**When context or credits run low, or the session ends:**
1. Append a dated entry to "Decisions log".
2. Overwrite "Current state" to match reality — what runs, what's stubbed,
   what's broken. Blunt beats optimistic.
3. Overwrite "Current phase" and "Next steps" as a concrete ordered checklist
   for someone with zero memory.
4. Note any new env vars, dependencies, or setup steps.
5. Never leave the repo in a state where `make dev` fails without flagging it
   at the top of "Current state".

Golden rule: if you had to figure it out, write it down. The log is cheap;
re-discovering isn't.

---

## 2. What we're building

An AI care agent that keeps elderly patients on their medication, delivered
entirely over WhatsApp so the patient installs nothing and learns nothing.

A caretaker registers on a web dashboard and enters their parent's medicines and
dose times. From then on the system messages the patient on WhatsApp at every
dose. The patient taps a button, types, or sends a voice note. Silence
escalates: a gentler reminder at 15 minutes, a WhatsApp alert to the caretaker
at 30 minutes. Every reply becomes a row in the adherence log, which becomes a
PDF the caretaker hands the doctor at the next visit.

---

## 3. Non-negotiable product principles

1. **WhatsApp is the patient's entire interface.** No app, no login, no learning
   curve. If a feature can't be delivered as a WhatsApp message, it doesn't
   belong in the patient-facing flow.
2. **Urdu and English are core, not bolted on.** Every patient-facing string
   exists in both languages from the start, in one localisation module.
3. **Never auto-trust AI output on anything clinical.** This applies to both
   prescription OCR and AI-fetched medicine information: both are always shown
   to the caretaker as an editable draft, and both require explicit
   confirmation before they activate or before the agent may repeat them to a
   patient. Not a shortcut, ever, even for demo purposes.
4. **Pre-generate voice notes.** TTS runs when a schedule is confirmed. The
   reminder attaches pre-existing audio. Reminders must feel instant.
5. **The dashboard is the one polished screen.** Judges linger on it.

---

## 4. Scope

The biggest risk in a 4-day build is doing too much. Anything not on the demo
screen in 5 minutes is not being built.

### In scope

1. Caretaker signs up (phone + OTP, a dev bypass is fine) and creates a family.
2. Caretaker adds a patient — name, WhatsApp number, preferred language, and
   the caretaker's **relation** to them (son, daughter, spouse, etc.).
3. Caretaker adds a medicine by name, dose times, and **tenure** — 7, 14, 30
   days, or a custom number — on the dashboard. Each medicine has its own
   tenure, so one patient can be on a 7-day antibiotic and a 30-day daily
   tablet at the same time, tracked separately. The system **auto-fetches**
   the medicine's purpose, food rule and typical timing via AI, shows it as an
   editable suggestion, and the caretaker confirms or corrects it before it
   goes live — the same human-in-the-loop pattern as prescription OCR (§3.3).
4. Patient receives an opt-in message on WhatsApp and confirms. **Sending it
   is the act of asking, so it sets `opted_in = false` and nothing else goes to
   that number until they answer** — a caretaker who never sends it has vouched
   for the patient and reminders start immediately, which is a decision they
   are allowed to make.
5. Scheduler fires a dose reminder as a WhatsApp **template** with two buttons
   and a pre-generated voice note.
6. Patient confirms via button, free text (Urdu / Roman Urdu / English), or
   voice note.
7. Silence 15 min → follow-up. Silence 30 min → caretaker alert on WhatsApp.
8. Late confirmation reclassifies missed → taken-late and notifies the caretaker.
9. Agent answers "what is this medicine for?" from a curated local reference and
   **refuses** anything clinical with the fixed line in §11.
10. Dashboard: family overview, today's doses, per-medicine adherence, event
    log, missed-dose timeline. Multiple caretakers may link to one patient.
11. **When a medicine's tenure ends** (its schedule reaches `end_date` with no
    further doses due), the system automatically generates **two PDF
    reports** for that medicine's course: a clinical one-page report for the
    doctor, and a plain-language summary for the caretaker. Both are also
    available on demand at any time from the dashboard, not only at course end.


### Stretch (Phase 7, only if Phase 6 is done and Day 3 hours remain)

Prescription photo → Qwen-VL extraction → caretaker confirmation → schedule.
Strongest Alibaba tie-in. Manual entry (#3) remains the reliable path.

### Out of scope — do not build, do not scaffold "for later"

Pharmacy integration · doctor portal · payment · multi-patient bulk management ·
native mobile app · refill reminders · snooze beyond "abhi nahi" · Punjabi /
Pashto / Sindhi · timezones beyond `Asia/Karachi` · migrations tooling · Docker
Compose · Kubernetes · websockets (poll every 5s) · admin panel · dark mode ·
unit-test coverage targets · rate limiting · multi-tenancy.

If you catch yourself building an abstraction for a second use case that does
not exist yet, delete it.

---

## 5. Non-negotiable invariants

1. **Every dose reminder is a WhatsApp template of category UTILITY.** Free-form
   sends only work inside an open 24-hour customer service window.
2. **The dose event ID travels in the button payload** (`TAKEN:<dose_id>`,
   `LATER:<dose_id>`). Never infer which dose a reply refers to from timing.
   *WhatsApp withdrew interactive buttons for non-official clients on
   2026-08-23, so there is usually no payload. The replacement rule is
   invariant 14 — resolve against pending state, never against the clock.*
3. **The webhook returns HTTP 200 within 2 seconds, before any processing.**
   Enqueue, then return.
4. **Every inbound message is deduplicated on Meta's `wa_message_id`** with a
   unique index.
5. **Dose events are idempotent.** A restart or retry never sends a second
   reminder for the same dose.
6. **All outbound HTTP to Meta goes through `app/whatsapp/client.py`.** No other
   module imports `httpx` to call graph.facebook.com.
7. **Voice notes are OGG/Opus.** Anything else renders as a file attachment and
   elderly users will not open it.
8. **The agent never diagnoses, changes a dose, recommends or substitutes a
   medicine, or interprets a symptom or test result.** Enforced in three places:
   system prompt, programmatic pre-send check, `tests/test_guardrails.py`.
9. **Medicine information the agent repeats to a patient is served only from a
   `medicine_reference` row with `confirmed = true`.** A row starts as an AI
   fetch, but a fetch is a *draft* — never surfaced to a patient and never
   usable by the agent until a caretaker has reviewed and confirmed it on the
   dashboard. The model may rephrase a confirmed row; it may never invent
   information or fall back to its own untethered knowledge at reply-time.
10. **No outbound message contains a dose figure not in the database.** Assert
    before send.
11. **Nothing claims the patient was observed taking a dose.** Every record and
    every report says "patient-reported".
12. **Every patient-facing string lives in `app/i18n/strings.py`** with `ur` and
    `en` keys. No inline copy in business logic.
13. **Nothing but the intro reaches a patient who has not opted in, and a reply
    is never gated.** Consent — not a hand-kept allowlist — is what stops a
    mistyped digit sending a stranger somebody's medical reminders: a wrong
    number is a perfectly valid `patient` row, so *"is this registered"* allows
    it and *"has a human on this handset replied"* does not. The intro must
    always get through or asking becomes impossible. And free text to a patient
    only ever comes from `agent.respond`, which runs *because they messaged
    us*, so `template is None` means "we are answering" and is always allowed —
    refusing to answer somebody who just wrote to you is not a safety measure.
    Enforced in `whatsapp/client.may_send`, on every outbound path.
14. **Which dose a reply means is resolved by MEDICINE, never by dose count.**
    Two open doses of one medicine are not a question — "I took it" can only
    mean that one, and the newest is what they were last reminded of. When two
    *medicines* are open and the reply names neither, ask which and name every
    option; do not claim not to have understood somebody who was perfectly
    clear. Counting doses instead of medicines made a twice-daily prescription
    unanswerable and told a patient "samajh nahi aaya" three times in ninety
    seconds.
15. **A wrong `taken` is the worst record this system can write.** It falsifies
    a medical log *and* switches off the escalation that would have caught it,
    so the mistake hides itself. Buying, collecting, having, or being about to
    take are not taking; a forwarded message is not an answer; and when unsure,
    ask. An unnecessary question costs one message.

---

## 6. Stack — all free

Every service below is genuinely free, has a free tier large enough for a
hackathon demo, or is covered by the Alibaba Cloud hackathon credits.

| Layer | Choice | Cost | Why |
|---|---|---|---|
| Backend | **Python 3.11 + FastAPI** | free | Only sensible glue for WhatsApp + Qwen + Whisper |
| Frontend | **Next.js 14 + Tailwind + shadcn/ui** | free | The one polished screen |
| Database | **Supabase Postgres** free tier | free (500 MB) | Managed, one URL, plenty for a demo |
| ORM | **SQLModel** + `create_all` | free | No Alembic |
| Scheduler | **APScheduler** in-process | free | Not Celery, not Function Compute |
| WhatsApp | **Meta Cloud API direct** (test number) | free | 5 whitelisted numbers, no BSP markup |
| LLM reasoning | **Qwen** via Alibaba Model Studio (DashScope) | hackathon credits | Sponsor platform |
| Vision (Phase 7) | **Qwen-VL** via DashScope | hackathon credits | Sponsor platform |
| ASR | **`faster-whisper`** running locally | free forever | Best free Urdu accuracy, no API key, no quota |
| TTS | **`edge-tts`** (Microsoft neural voices), `ur-PK-UzmaNeural` | free forever | Best free Urdu voice, and needs no account, card or API key |
| Object storage | **Supabase Storage** free tier | free (1 GB) | Same platform as the DB |
| Backend host | **Alibaba Cloud ECS** small instance | hackathon credits | Sponsor platform, and it's the demo requirement |
| Frontend host | **Vercel** free tier | free | One `git push` deploys the dashboard |
| Dev tunnel | **ngrok** free | free | Local webhook while iterating |
| PDF | **fpdf2** + `uharfbuzz` | free | Pure Python, no system libraries, and shapes Urdu correctly |
| Medicine lookup | **Qwen** (DashScope) with web search grounding if available | hackathon credits | Fetches a *draft* only — never trusted until a caretaker confirms it |

**On the voice stack specifically:**
- `faster-whisper` runs on CPU and costs nothing per call — no quota to
  exhaust the night before the demo. **Use `small`, not `base`.** Measured
  2026-08-22: `base` transcribed "ابھی نہیں" (*abhi nahi*, "not now") as
  "اب ہی" (*ab hi*, "right now") — inverting the meaning of a dose reply.
  `small` transcribes it exactly. Short utterances are the *hard* case for
  Urdu ASR, not the easy one; longer phrases like "seene mein dard ho raha
  hai" come back verbatim on both models.
- `edge-tts` reaches Microsoft's neural voices — the same ones Azure sells —
  with **no account, no card and no API key**. Two Pakistani Urdu voices exist:
  `ur-PK-UzmaNeural` (female, the one we use) and `ur-PK-AsadNeural` (male).
  Output is MP3, converted to OGG/Opus mono with PyAV, which is already present
  as a `faster-whisper` dependency — so no ffmpeg binary is needed on the ECS
  box either.
- *Replaced Google Cloud TTS on 2026-08-22 because it requires a card on file.
  Quality is equivalent; the dependency tree is smaller. See PROJECT_LOG.md.*
- **Fallback if edge-tts is blocked or the venue has no internet:** Piper TTS
  locally (`ur_PK` ONNX voice). Lower quality, but offline and free forever.
  The official-API path, if this ever leaves the hackathon, is Azure Speech's
  F0 tier — identical voices, 500k characters a month free.
- **Do not silently swap the voice stack.** If a service can't be configured,
  log it in `PROJECT_LOG.md` and ask before switching.

**On the PDF stack specifically:**
- *Replaced WeasyPrint on 2026-08-23.* WeasyPrint needs GTK/Pango, which pip
  does not ship on Windows — `import weasyprint` raised
  `OSError: cannot load library 'libgobject-2.0-0'` on the dev machine, so the
  reports could not be built or checked locally at all. fpdf2 is pure Python
  and behaves identically on Windows and the Ubuntu ECS box, with nothing to
  install per teammate and no apt packages in Phase 8.
- **`uharfbuzz` is not optional.** fpdf2 only shapes Arabic script when
  `set_text_shaping(True)` is on and uharfbuzz is importable. Without it Urdu
  renders as disconnected letters in left-to-right order — unreadable. The
  patient's own words are quoted verbatim in the doctor report, and ASR
  returns Urdu script, so this path is always exercised.
- **The Urdu font is bundled in the repo** at
  `backend/app/reports/fonts/`, not taken from the system. Windows has Arial
  with Arabic coverage and a bare Ubuntu box has neither it nor Noto, so
  relying on system fonts would mean the report renders here and comes out
  blank on ECS.

If anything in this table changes, update the table AND log the reason.

---

## 7. Repository layout

```
mednuskha/
├── AGENTS.md                 # this file
├── PROJECT_LOG.md            # session-to-session state
├── SCHEMA.md                 # locked at end of Phase 0
├── README.md                 # written in Phase 8
├── .env.example
├── Makefile                  # make dev / make test / make seed
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py           # FastAPI app, router mounting
│   │   ├── config.py         # env vars, one Settings object
│   │   ├── models.py         # ALL SQLModel tables — FROZEN end of Phase 0
│   │   ├── db.py             # engine + session
│   │   ├── i18n/strings.py   # every patient-facing string, ur + en
│   │   ├── whatsapp/
│   │   │   ├── client.py     # only module talking to graph.facebook.com
│   │   │   ├── webhook.py    # GET verify + POST receive, 200 fast
│   │   │   └── parser.py     # Meta payload -> InboundMessage
│   │   ├── scheduler/
│   │   │   ├── ticker.py
│   │   │   └── state_machine.py
│   │   ├── agent/
│   │   │   ├── interpret.py
│   │   │   ├── respond.py
│   │   │   ├── guardrails.py
│   │   │   └── knowledge.py
│   │   ├── vision/ocr.py     # Phase 7 stretch
│   │   ├── voice/
│   │   │   ├── asr.py        # faster-whisper wrapper
│   │   │   ├── tts.py        # edge-tts wrapper, pre-generates
│   │   │   └── store.py      # where the voice notes live
│   │   ├── storage.py        # Supabase Storage, shared by reports + voice
│   │   ├── reports/doctor_pdf.py
│   │   └── api/routes.py     # REST for the dashboard
│   └── tests/
│       ├── test_guardrails.py
│       └── test_state_machine.py
├── frontend/                 # Next.js
│   ├── app/
│   ├── components/
│   └── lib/api.ts
└── scripts/
    ├── send_test.py
    └── seed_demo.py
```

---

## 8. Data model — frozen at end of Phase 0

Eleven tables. Column-level detail goes in `SCHEMA.md` once locked.

```
family, caretaker, patient, medicine, schedule, dose_event,
message_log, symptom_report, prescription, medicine_reference, report
```

`caretaker` — includes `relation` (free text: "son", "daughter", "spouse",
"caregiver", etc.), set when the caretaker links to a patient. Shown throughout
the dashboard and used in message copy ("aap ke bete ne...").

`schedule` — one row per medicine's course. Includes `duration_days` (the
caretaker picks 7 / 14 / 30 / custom on the add-medicine form — see Phase 4),
`start_date`, and a computed `end_date = start_date + duration_days`. Each
medicine on a patient has its own `schedule` row, so a patient can be on a
7-day antibiotic and a 30-day blood pressure tablet at once, each tracked and
reported on independently.

`medicine_reference` — the cache of AI-fetched, caretaker-confirmed medicine
knowledge: `id, canonical_name, aliases (JSON list), purpose_ur, purpose_en,
food_rule, common_timing, source ("ai_fetched" | "caretaker_edited"),
confirmed (bool, default false), confirmed_by (caretaker_id, nullable),
fetched_at, confirmed_at`. One row per unique medicine name across the whole
system — fetched once, reused by every patient who is later prescribed the
same medicine, with each new caretaker still shown the existing draft to
confirm for their own patient on first use.

`report` — one row per generated PDF: `id, patient_id, medicine_id (nullable —
null means "whole patient"), kind ("doctor" | "caretaker"), period_start,
period_end, storage_key, generated_at, trigger ("course_end" | "on_demand")`.

`dose_event.state` transitions:
`SCHEDULED → SENT → AWAITING_REPLY → REMINDED_AGAIN → {TAKEN | TAKEN_LATE | MISSED | SKIPPED}`

State transitions live **only** in `state_machine.py`. Nothing else mutates
`dose_event.state`.

---

## 9. Frozen interface contracts — agreed end of Phase 0

Every later phase codes against these. Do not change a signature without
updating this file first.

```python
# whatsapp/client.py
async def send_template(to, template, lang, body_vars,
                        button_payloads=None) -> str: ...
async def send_text(to, body) -> str: ...
async def send_buttons(to, body, buttons: list[tuple[str, str]]) -> str: ...
async def send_voice(to, storage_key_or_bytes) -> str: ...
async def download_media(media_id) -> bytes: ...

# whatsapp/parser.py
@dataclass
class InboundMessage:
    wa_message_id: str
    from_number: str
    kind: Literal["text", "button", "audio", "other"]
    text: str | None
    payload: str | None
    media_id: str | None
    timestamp: datetime

# agent/interpret.py
@dataclass
class Intent:
    kind: Literal["taken", "not_taken", "later", "question",
                  "symptom", "emergency", "unclear", "stop"]
    dose_id: str | None
    reason: str | None
    confidence: float
async def interpret(msg, patient, open_doses) -> Intent: ...

# agent/respond.py
async def respond(intent, patient) -> None: ...

# agent/knowledge.py
async def fetch_draft(name: str) -> MedicineInfoDraft: ...
    # Calls Qwen. Returns a draft. NEVER writes confirmed=true.
    # NEVER called from the patient-facing reply path — fetch happens only
    # when a caretaker adds a medicine on the dashboard.
def get_confirmed(name: str) -> MedicineInfoDraft | None: ...
    # DB read only. This is the ONLY function the agent may call at
    # reply-time. Returns None if no confirmed row exists.
async def save_confirmed(name: str, info: MedicineInfoDraft,
                         caretaker_id: str) -> None: ...
    # Called only from the dashboard confirm action.
```

---

## 10. WhatsApp integration rules

Base URL: `https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages`. **Verify
the current API version in Meta's docs before writing the client — do not trust
a version number recalled from memory.**

- Numbers are sent with no `+` and no leading zero: `923001234567`.
- Webhook `GET /webhook` returns `hub.challenge` as **plain text**, not JSON.
- Button taps arrive at `entry[0].changes[0].value.messages[0].button.payload`
  from templates, and `.interactive.button_reply.id` from interactive messages.
  Handle both shapes.
- Media download is two steps: `GET /v23.0/{media_id}` for a URL, then fetch
  that URL **with the Bearer token attached**. Plain fetch returns 401.
- Templates live in Business Manager, not code. Code references them by name.

### Templates to submit at the start of Phase 0 (approval isn't instant)

| Name | Category | Body | Buttons |
|---|---|---|---|
| `dose_reminder` | UTILITY | `{{1}} ji, {{2}} baj gaye — {{3}} lene ka waqt hai. {{4}}` | `Le li ✓` / `Abhi nahi` |
| `dose_followup` | UTILITY | `{{1}} ji, sirf yaad dila rahe hain — {{2}} abhi baaki hai.` | `Le li ✓` / `Abhi nahi` |
| `caretaker_alert` | UTILITY | `{{1}} ne aaj {{2}} ki {{3}} confirm nahi ki. Do baar yaad dilaya gaya hai.` | — |
| `patient_optin` | UTILITY | `Assalam-o-alaikum {{1}} ji. {{2}} ne aap ke liye dawai ki yaad-dahani set ki hai. Shuru karne ke liye "HAAN" likhein.` | — |

---

## 11. Agent rules

The agent turns a messy human reply into one `Intent` and produces one short
warm message back. It is not a chatbot.

- Understands Urdu script, Roman Urdu and English. Replies in whatever the
  patient used.
- One idea per message. The reader is 68 and reading slowly.
- Names the medicine and strength every time.
- Never scolds. A missed dose gets warmth and a second chance.
- On low confidence (< 0.6), asks one short clarifying question. Never guesses.

**Guardrails (`app/agent/guardrails.py`)** run on every outbound message before
send. Block and substitute the fixed refusal if the draft:
- contains a dosage instruction not matching the patient's schedule rows;
- recommends, substitutes, increases, decreases, starts or stops any medicine;
- offers a diagnosis or interprets a symptom;
- responds to emergency keywords (chest pain, saans, behosh, bleeding) with
  anything other than the fixed emergency copy + an immediate caretaker alert.

Fixed refusal: *"Main ye faisla nahi kar sakta — ye doctor sahab ka kaam hai.
Main abhi {caretaker} ko bata deta hoon, aur ye baat aap ki agli report mein bhi
likh di jayegi."*

`tests/test_guardrails.py` has at least 12 adversarial cases including
third-person framing, hypotheticals, and Roman Urdu phrasings. This test file is
a demo asset — judges in a healthcare track will ask about safety.

---

## 12. Conventions

- **Read before writing.** Open the files you're about to change.
- **Small commits, one concern each.** `feat(scheduler): ...`, `fix(whatsapp): ...`.
- **No new dependencies** without saying so explicitly. Stack in §6 is final.
- **No placeholder code.** If you can't finish, say so; don't commit a stub.
- **Log every state transition and every outbound send** with the dose id. These
  logs are the only tool that works when the demo misbehaves at 11pm.
- **Fetch docs, don't recall.** Especially for Meta and Google Cloud APIs.
- **Ask before deleting or restructuring anything you didn't write.**

Every phase ends with a runnable system. No phase produces "scaffolding".

---

## 13. Environment variables

Names only. `.env` is gitignored.

```
# WhatsApp
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_WABA_ID=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_API_VERSION=v23.0

# Alibaba Cloud
DASHSCOPE_API_KEY=                  # Qwen + Qwen-VL

# Voice
TTS_VOICE=ur-PK-UzmaNeural          # edge-tts; ur-PK-AsadNeural is the male voice
WHISPER_MODEL=small                 # "base" inverts Urdu negations - see PROJECT_LOG

# Data
DATABASE_URL=                       # Supabase Postgres connection string
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_STORAGE_BUCKET=voice-notes

# App
TIMEZONE=Asia/Karachi
FOLLOWUP_MINUTES=15                 # 1 during the demo
ESCALATE_MINUTES=30                 # 2 during the demo
NEXT_PUBLIC_API_BASE=
```

---

## 14. The phase plan

Ten sequential phases, one Claude Code seat. For each phase:
**Claude prompt** (paste after the master prompt in §0) · **Done when** (the gate
to the next phase) · **Your turn** (what the humans do afterwards).

Rough pacing: Day 1 = Phases 0–1 · Day 2 = Phases 2–4 · Day 3 = Phases 5–7 ·
Day 4 = Phases 8–9.

---

### Phase 0 — Bootstrap

**Claude prompt:**
> Create the repo skeleton from §7, `requirements.txt`, `.env.example` from §13,
> and a `Makefile` with `dev`, `test`, `seed` targets. Then:
> - `backend/app/config.py` — one Settings object loading the env.
> - `backend/app/db.py` — engine + session dependency for Supabase Postgres.
> - `backend/app/models.py` — all nine tables from §8 with sensible columns,
>   proper foreign keys, and UNIQUE indexes on `dose_event.idempotency_key`
>   and `message_log.wa_message_id`.
> - Every other backend file in §7 as an empty module with only its imports
>   and the frozen signatures from §9 — signatures and docstrings, no
>   implementations.
> - Scaffold the Next.js frontend with Tailwind + shadcn/ui, one stub page at
>   `/`, and `lib/api.ts` reading `NEXT_PUBLIC_API_BASE`.
>
> Write `SCHEMA.md` with the column-level schema. Run `make dev`, confirm both
> processes start and `GET /api/health` returns 200. Create `PROJECT_LOG.md`
> from §16 and fill it in. Stop there.

**Done when:** `make dev` starts both processes, `curl /api/health` returns 200,
every file in §7 exists, and `SCHEMA.md` + `PROJECT_LOG.md` are written.

**Your turn:**
1. **Do this first, before anything else:** create a Meta Developer app
   (developers.facebook.com → Business → add the WhatsApp product). Save
   `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_WABA_ID`. In WhatsApp → API Setup,
   whitelist three team numbers on the free test number and enter each
   confirmation code.
2. In Meta Business Settings, create a **System User**, assign the WABA asset,
   generate a **permanent token** with `whatsapp_business_messaging` and
   `whatsapp_business_management`. This replaces the 24-hour temp token. Save
   as `WHATSAPP_TOKEN`. Invent a random string for `WHATSAPP_VERIFY_TOKEN`.
3. In WhatsApp Manager → Message Templates, **submit all four templates from
   §10 right now.** Approval takes hours, sometimes a day. The build blocks on
   this by Phase 2 — nothing else you do today matters more.
4. Create the Supabase project (free tier). Copy `DATABASE_URL`, `SUPABASE_URL`,
   `SUPABASE_ANON_KEY`. Create a private `voice-notes` storage bucket.
5. Create a DashScope account (dashscope.aliyun.com), redeem the hackathon
   credit code, save `DASHSCOPE_API_KEY`.
6. Fill `.env`, run `make dev` yourself, confirm it works. Commit and push.

---

### Phase 1 — WhatsApp transport (a real message on a real phone)

**Claude prompt:**
> Build the complete `backend/app/whatsapp/` package against the §9 signatures.
> Before writing the client, fetch Meta's current Cloud API reference for
> sending template messages and for the webhook payload shape — do not write
> field names from memory. The webhook must return HTTP 200 before any
> processing (hand off to a background task) and deduplicate on
> `wa_message_id` using the DB unique index. Persist every inbound and
> outbound message to `message_log`. Write `scripts/send_test.py` — a CLI that
> sends `dose_reminder` to a phone number passed as an argument. Do not touch
> `agent/`, `frontend/`, or `reports/`. Update `PROJECT_LOG.md`.

**Done when:**
- `python scripts/send_test.py 92300XXXXXXX` sends the template and it arrives.
- Tapping "Le li ✓" or "Abhi nahi" writes a `message_log` row with the correct
  button payload.
- Delivering the same webhook payload twice produces one row, not two.

**Your turn:**
1. Confirm `dose_reminder` and `patient_optin` are approved in WhatsApp Manager.
   If not, wait — there is no point continuing.
2. Run `ngrok http 8000`. Copy the https URL.
3. Meta App Dashboard → WhatsApp → Configuration: set the callback URL to
   `<ngrok-url>/webhook` and the verify token to your `WHATSAPP_VERIFY_TOKEN`.
   Subscribe to the `messages` field.
4. Run the test script against your own number. Tap both buttons. Check the DB.
5. **If this doesn't work by end of Day 1, stop everything and fix it.** Every
   remaining phase sits on top of it.

---

### Phase 2 — The dose loop

**Claude prompt:**
> Build `scheduler/ticker.py` and `scheduler/state_machine.py`. On startup and
> once a minute, materialise dose events for the next 24 hours from active
> schedules, idempotent on `(schedule_id, scheduled_at)`. Fire a
> `dose_reminder` template at each event's scheduled minute
> (`SCHEDULED → SENT → AWAITING_REPLY`). On a button reply carrying that
> event's dose id, transition to TAKEN and cancel the escalation chain. With
> no reply after `FOLLOWUP_MINUTES`, send `dose_followup` and transition to
> REMINDED_AGAIN. With no reply after `ESCALATE_MINUTES` total, transition to
> MISSED and send `caretaker_alert`. A late reply on a MISSED event
> reclassifies it to TAKEN_LATE and sends a free-form resolution message to
> the caretaker. Both windows come from env vars, never hardcoded. State
> transitions happen only in `state_machine.py`. Log every transition with the
> dose id. Guard against APScheduler starting twice under `--reload`. Update
> `PROJECT_LOG.md`.

**Done when:** you schedule a dose two minutes out, walk away, and the full
taken-path *and* missed-path run unattended with correct DB rows and correct
WhatsApp messages on both phones — plus the late-reply reclassification.

**Your turn:**
1. Insert one test family, caretaker, patient, medicine and schedule with a dose
   two minutes out.
2. With `FOLLOWUP_MINUTES=1` and `ESCALATE_MINUTES=2`, verify all three paths.
3. **This is the milestone that matters most.** If Day 2 ends here you have a
   demoable product and everything after is upside. Protect it.

---

### Phase 3 — Agent understanding

**Claude prompt:**
> Implement `agent/interpret.py` and `agent/respond.py` against §9, using Qwen
> via DashScope. Handle every `Intent.kind`: taken, not_taken, later, question,
> symptom, emergency, unclear, stop. Understand Urdu script, Roman Urdu and
> English. Handle the messy real replies: "already took it", "the strip is
> finished", "feeling unwell", "chakkar aa rahe hain", "STOP". On confidence
> below 0.6 return `unclear` — respond asks one short clarifying question in
> the patient's language. `interpret` runs async, off the webhook request path.
> Every outbound message passes through `guardrails.py` first, with no
> exceptions.
>
> Also build `agent/knowledge.py` with three functions against the §9
> signatures: `fetch_draft(name)` calls Qwen (use its web search tool if
> DashScope exposes one for grounding; otherwise its trained knowledge) and
> returns a structured draft — purpose in simple Urdu and English, food rule,
> typical timing — **without ever marking it confirmed**. `get_confirmed(name)`
> is a plain DB read of `medicine_reference` where `confirmed = true`, and is
> the *only* function `respond.py` may call when answering a patient's
> question — if it returns `None`, the agent says it doesn't have confirmed
> information yet and offers to notify the caretaker, it never falls back to
> asking Qwen directly. `save_confirmed(name, info, caretaker_id)` writes the
> row with `confirmed = true`, called only from the dashboard's confirm
> endpoint you'll build in Phase 4.
>
> Also write `agent/guardrails.py`, `i18n/strings.py` with every patient-facing
> string in `ur` and `en`, and `tests/test_guardrails.py` with at least 12
> adversarial cases per §11 — include at least one case where
> `get_confirmed` returns `None` and confirm the agent does not invent an
> answer. Wire the whole thing to the webhook so a typed or Roman Urdu reply
> has the same effect as tapping the button. Update `PROJECT_LOG.md`.

**Done when:**
- Replying "haan le li" or "yes taken" transitions the dose to TAKEN, exactly
  as tapping the button does.
- "yeh dawai kis liye hai?" gets a plain-language answer sourced only from a
  `confirmed = true` row — never a live Qwen call at reply-time.
- Asking about a medicine with no confirmed row gets the "don't have confirmed
  information yet" fallback, not an invented answer.
- "should I double the dose?" gets the fixed refusal.
- All 12+ guardrail tests pass.

**Your turn:**
1. Have three people each throw an edge-case reply at the test phone. Log every
   misfire in `PROJECT_LOG.md`.
2. Confirm the refusal fires on: dose change, substitution, diagnosis, and a
   Roman Urdu phrasing of one of them.
3. When you test the add-medicine flow in Phase 4, actually read each
   AI-fetched draft before hitting confirm — you are the safety check, not a
   rubber stamp. This is the one place in the whole system where a plausible-
   sounding hallucination becomes a patient-safety issue rather than a bug.

---

### Phase 4 — Dashboard (the polished screen)

**Claude prompt:**
> Build the Next.js dashboard, plus the REST endpoints it needs in
> `backend/app/api/routes.py`. Design principles: minimal chrome, generous
> whitespace, one clear action per screen, mobile-responsive since we may demo
> from a phone. Screens:
> 1. Family overview — patients, each with today's adherence at a glance.
> 2. Patient page — today's doses with live status pills (SCHEDULED, SENT,
>    AWAITING_REPLY, TAKEN, TAKEN_LATE, MISSED), the medicines list,
>    per-medicine adherence % over 14 days, and the full event log below.
> 3. Add-patient form (name, WhatsApp number, language, and the caretaker's
>    **relation** to the patient), and an **add-medicine flow** that works like
>    this: the caretaker types a medicine name and clicks "Look up" → the
>    frontend calls a new `POST /api/medicines/lookup` endpoint → the backend
>    calls `agent.knowledge.fetch_draft(name)` (or reads an existing
>    `medicine_reference` row if one already exists, skipping the AI call) →
>    the draft (purpose, food rule, typical timing) is shown in editable text
>    fields, never as read-only text → the caretaker edits anything wrong,
>    picks the actual dose times, and picks the **tenure** — a 7 / 14 / 30 day
>    quick-select or a custom number of days, which sets `schedule.start_date`
>    (today) and `schedule.duration_days` → clicks "Confirm & add" → this calls
>    `POST /api/medicines` which saves `medicine_reference` via `save_confirmed`
>    (if not already confirmed) and creates the patient's `medicine` +
>    `schedule` rows in one transaction. The medicine is never added to the
>    patient without this confirm step, even if a `medicine_reference` row
>    already existed from another patient — always show it for review. A
>    patient can have several medicines active at once, each with its own
>    independent tenure — show each one's remaining days on the patient page.
>
> Poll `/api/patients/:id/today` every 5 seconds while the page is open. Use
> shadcn `Card`, `Table`, `Badge`, `Button` — do not hand-roll basics. Do not
> touch `agent/interpret.py`, `agent/respond.py`, `scheduler/`, or `whatsapp/`.
> You will touch `agent/knowledge.py` only to call it, not to change its
> signatures. Update `PROJECT_LOG.md`.

**Done when:** the dashboard shows real DB data, refreshes every 5 seconds, and
adding a medicine — type name, look up, review/edit the draft, set dose times,
confirm — produces a real `medicine_reference` row and a real WhatsApp
reminder at its scheduled time.

**Your turn:**
1. Walk the dashboard as if you were the caretaker in the demo. Note anything
   that looks unfinished. Fix only what's demo-critical — no dark mode, no
   animations, no settings page.
2. Add your three demo medicines through the real flow, not a seed script, at
   least once — read every fetched draft before confirming. This doubles as
   your safety check on the AI-fetched content and as demo rehearsal.

---

### Phase 5 — Voice

**Claude prompt:**
> Add `voice/tts.py` and `voice/asr.py`.
>
> `tts.py` wraps `edge-tts` with the `ur-PK` voice named in `TTS_VOICE`.
> Output must be OGG/Opus mono — convert the MP3 edge-tts returns using PyAV.
> No API key, account or card is involved. Run it in a background task when a schedule is confirmed: generate
> one audio file per unique dose text, upload to Supabase Storage under
> `voice-notes/`, and save the storage key on the dose event. Cache by
> `(medicine, dose_time)` so we don't regenerate identical audio. When a
> reminder fires, `send_voice` attaches the pre-existing file — never
> synthesise inline in the reminder path.
>
> `asr.py` wraps `faster-whisper` with the model from `WHISPER_MODEL`. When an
> inbound `audio` message arrives, download the media, transcribe as Urdu, and
> feed the text into `agent.interpret` exactly as if it were a text reply.
>
> Wire both into the existing paths without changing any signature. Update
> `PROJECT_LOG.md`.

**Done when:**
- A live reminder arrives with a natural-sounding Urdu voice note.
- Replying with an Urdu voice note ("le li hai") transitions the dose to TAKEN.
- Asking "yeh dawai kis liye hai?" by voice gets a spoken reply.

**Kill switch:** if edge-tts is unusable by **18:00 on Day 3**, switch
`tts.py` to Piper (`ur_PK` ONNX voice) and log the swap. If Piper also blocks,
ship text-only, hand-record one voice reply for the demo, and say in the pitch
that voice is tuned during the pilot. Do not spend Day 4 on this.

**Your turn:**
1. Nothing to set up — `edge-tts` needs no account, card or key. Just listen
   to the generated voice notes and say whether the voice works for a
   68-year-old listener.
2. Run `faster-whisper` once locally on an Urdu sample to warm the model cache
   and confirm recognition works before Claude wires it in.

---

### Phase 6 — Reports: doctor and caretaker, generated at course end

**Claude prompt:**
> Build `reports/doctor_pdf.py` and `reports/caretaker_pdf.py` using
> fpdf2, both against the `report` table from §8.
>
> **Doctor report** — one page, clinical and neutral: patient name, medicine
> name and tenure (start date, duration, end date), adherence percentage for
> that medicine's course, timing distribution (on time / late / missed),
> missed-dose log with the patient's stated reason quoted verbatim, symptoms
> reported verbatim, and an explicit line stating these are patient-reported
> confirmations, not observed ingestion.
>
> **Caretaker report** — one page, warm and plain-language: the same course,
> "X of Y doses taken", which time of day was hardest, any streaks worth
> celebrating, and a gentle note about anything missed — no clinical jargon,
> no tables of statistics.
>
> Add a scheduler job (in `scheduler/ticker.py`, alongside the dose ticker)
> that checks once a day for any `schedule` whose `end_date` has passed with
> no further doses due, and — if reports don't already exist for that
> schedule — generates both PDFs automatically, stores them in Supabase
> Storage, writes two `report` rows with `trigger = "course_end"`, and sends
> the caretaker a WhatsApp message with a link to both. Also add
> `GET /api/patients/:id/report.pdf?kind=doctor|caretaker&medicine_id=...`
> so either report can be generated on demand at any time
> (`trigger = "on_demand"`), and matching buttons on the patient dashboard
> page. Update `PROJECT_LOG.md`.

**Done when:**
- Both report buttons on the dashboard download real PDFs with real numbers
  for a patient with 14 days of history.
- Manually setting a test schedule's `end_date` to yesterday and running the
  daily check job produces both PDFs automatically and a WhatsApp message to
  the caretaker with both links, without any button click.

**Your turn:**
1. Read both PDFs as if you were the doctor, then as if you were the
   caretaker. The doctor version should read like a clinical handout; the
   caretaker version should read like a caring update, not a spreadsheet.
   Anything unclear or padded? Log it — these are the artifacts the pitch
   closes on.

---

### Phase 7 — Prescription OCR (stretch, only if hours remain)

**Claude prompt:**
> Build `vision/ocr.py`. `POST /api/patients/:id/prescriptions` accepts an
> image upload, sends it to Qwen-VL via DashScope with a structured-output
> prompt requesting a JSON list of `{name, strength, form, dose_times,
> food_rule, duration_days}`, and stores the raw response on
> `prescription.raw_extraction`. Show the extracted list on a confirmation
> screen where the caretaker can edit any field or delete a line. Only on
> "Confirm" do we insert `medicine` and `schedule` rows and set
> `confirmation_state = "confirmed"`. **Under no circumstances is a schedule
> activated without caretaker confirmation** — not in dev, not for the demo.
> That is invariant #3. If Qwen-VL isn't extracting reliably by 22:00, log it
> and stop. Update `PROJECT_LOG.md`.

**Done when:** uploading a real prescription photo shows an editable extracted
list, and confirming it activates a real schedule.

**Your turn:**
1. Photograph two or three real Pakistani prescriptions for testing.
2. Try each. If it isn't consistently working by 22:00 on Day 3, cut it —
   manual entry stays the demo path and OCR becomes a roadmap slide.

---

### Phase 8 — Deploy

**Claude prompt:**
> Prepare deployment:
> - A minimal `Dockerfile` for the FastAPI backend (python:3.11-slim, install
>   requirements, copy app, run uvicorn).
> - `README.md` with exact setup steps: prerequisites, required `.env` values,
>   `make dev`, and deployment steps.
> - `scripts/seed_demo.py` creating one caretaker, one patient, three real
>   medicines, and 14 days of realistic backdated dose events with a believable
>   mix of taken, taken-late and missed — so the PDF and dashboard have
>   something worth showing.
> - An ASCII architecture diagram in the README.
> Update `PROJECT_LOG.md`.

**Done when:** a fresh clone runs on a teammate's laptop from the README alone,
and `make seed` produces a demo-worthy database in one command.

**Your turn (deployment is yours, not Claude's):**
1. Provision an Alibaba Cloud ECS instance on hackathon credits — 2 vCPU / 4 GB,
   Ubuntu 22.04, ports 80 and 443 open.
2. Build and run the backend container there, or `scp` and run under systemd —
   whichever the team is faster at.
3. Point a subdomain at the instance IP. Use Caddy for automatic TLS, or
   certbot if you prefer nginx.
4. Set every env var on the server. Do not commit them.
5. Deploy the frontend: `vercel --prod` from `frontend/`, with
   `NEXT_PUBLIC_API_BASE` set to the backend HTTPS URL in Vercel's env settings.
6. Repoint Meta's webhook to `https://<backend>/webhook` and re-verify.
7. Send yourself a reminder from the deployed instance. Retire ngrok.

---

### Phase 9 — Freeze, rehearse, record

**Hard feature freeze at 12:00 on Day 4.** After that: crash fixes only.

**Claude prompt:**
> We are frozen — no new features. Read §15 and `PROJECT_LOG.md`. Walk the demo
> script end to end and report every point where the system behaves differently
> from it. Fix crashes and incorrect data only. For anything cosmetic, tell me
> and leave it. Update `PROJECT_LOG.md` with the final state.

**Your turn:**
1. Run the demo script (§15) on the deployed system, **five times on real
   phones**. Every run must succeed.
2. Record a screen + phone-camera video of one perfect run. Live demos fail on
   conference wifi; the video is insurance, not defeat.
3. Rehearse the 5-minute pitch against the deck three times with a timer.
4. Submit early. Never in the last hour.

---

## 15. Demo script

For the demo, set `FOLLOWUP_MINUTES=1` and `ESCALATE_MINUTES=2` in the deployed
env. Neither is ever hardcoded.

1. Caretaker dashboard, one patient, three medicines already configured. *(20s)*
2. Trigger a dose. Template arrives on the real phone with a voice note. Tap
   "Le li". Dashboard updates live. *(45s)*
3. Trigger a second dose. Stay silent. Follow-up arrives with its voice note.
   *(45s)*
4. Stay silent. Caretaker's phone receives the escalation alert. **This is the
   moment that sells it.** *(30s)*
5. Voice note in Urdu: "yeh dawai kis liye hai?" Play the spoken reply. *(40s)*
6. Ask the agent to double the dose. It refuses and offers to notify the
   caretaker. *(25s)*
7. (If Phase 7 shipped.) Upload a prescription photo, show the extracted JSON
   and the confirmation screen. *(30s)*
8. Open both reports — the caretaker's plain-language summary, then the
   doctor's clinical PDF. Close on the adherence figure. Mention that these
   generate automatically the moment a medicine's course ends, not just on
   demand. *(25s)*

---

## 16. `PROJECT_LOG.md` template

If it doesn't exist, create it with exactly this structure:

```markdown
# MedNuskha — Project Log

## Current state
(What runs right now. What's stubbed or mocked. What's broken. Blunt beats optimistic.)

## Current phase
(Phase N from AGENTS.md §14, and exactly what's left within it.)

## Next steps
(Concrete, ordered, actionable. Written for someone with zero memory of this project.)

## Environment / setup
(Required env vars, accounts, API keys — names only, never actual secret values.
Setup commands. Which WhatsApp templates are approved and which are pending.)

## Gotchas discovered
(Bullet list. Anything that took more than a couple of minutes to figure out.
Future sessions re-hit these otherwise.)

## Decisions log
(Reverse chronological, append-only.)

### YYYY-MM-DD — Session <n>
- What was done
- Key decisions made and why
- Blockers hit and how (or whether) they were resolved
- Anything the next session needs to know before touching this area
```

"Current state", "Current phase" and "Next steps" are overwritten each session.
"Gotchas" grows. "Decisions log" is append-only history.

---

## 17. Things that will go wrong (and the fix)

- **Templates not approved by Phase 1.** Submit at the very start of Phase 0. If
  still pending, dev-loop by messaging the bot first (which opens a 24-hour
  window) and using `send_text` instead of `send_template`.
- **ngrok URL changes on restart** and the webhook silently stops. If you
  restart ngrok, re-save Meta's webhook config.
- **Double-processed replies** because the webhook was slow. If the
  `wa_message_id` unique index rejected a duplicate, that's correct behaviour,
  not a bug.
- **APScheduler fires jobs twice** after a reload — uvicorn `--reload` starts two
  workers. Guard scheduler start-up, or run the scheduler process without
  `--reload`.
- **Qwen latency inside the webhook** blocks the 200. `interpret` always runs in
  a background task.
- **Google TTS quota burned** by regenerating audio every run. Cache by
  `(medicine, dose_time)` — one file per unique dose text, not per event.
- **Supabase free tier pauses** the project after inactivity. Ping it from the
  ECS instance every few minutes with a cron.
- **A test number gets rate-limited** from repeated testing. Keep a spare
  whitelisted number.
- **Someone's laptop is the demo environment.** By Phase 8 the demo runs from
  the deployed URL, on someone else's machine, from a clean clone.
