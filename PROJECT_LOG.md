# MedNuskha — Project Log

## Current state

**Phase 0 is complete and the gate passes.** Verified this session, not assumed:

- `backend/.venv` built on **Python 3.14.4**; all of `requirements.txt` installed.
- Backend boots. `GET /api/health` returns **200** with an honest body reporting
  which env vars are missing.
- Frontend `npm run build` compiles clean with types checked; `npm run dev`
  serves on :3000.
- Both run together, and the dashboard **successfully fetches the backend
  across origins** (CORS confirmed working in a real browser, not just curl).
- `pytest` runs green: 2 skipped, 0 failed.

**What is real code:** `config.py`, `db.py`, `models.py` (all 11 tables),
`main.py`, `frontend/lib/api.ts`, `frontend/app/page.tsx`.

**What is a stub:** every other backend module. Each has its frozen §9
signature, a docstring explaining what it must do and which invariants apply,
and a body that `raise NotImplementedError("Phase N — …")`. Nothing silently
returns a wrong answer or `pass`es. The two test files skip at module level
with the phase named, so `make test` is green rather than red-by-default — the
adversarial case lists are already written out in them as data.

**What is broken / not yet possible:**

- **Database is LIVE.** Supabase Postgres 17.6, region ap-northeast-2 (Seoul),
  reached over the **session pooler on port 5432**. All 11 tables created by
  `init_db()` on first boot, both unique constraints present
  (`uq_dose_event_idempotency_key`, `uq_message_log_wa_message_id`).
  `/api/health` reports `"database": "connected"`.
- **No WhatsApp — BLOCKED.** The team hit a problem creating the Meta
  Developer / Business account. No app, no token, no templates submitted. The
  exact error has not been captured yet. Phase 1 is written but cannot be
  verified until this clears. See "Current phase".
- **WeasyPrint installs but does not import on Windows** — needs the GTK
  runtime. Blocks Phase 6 on a Windows dev machine. See Gotchas.
- `make seed` exits 1 with a clear message; it lands in Phase 8.

## Current phase

**Phases 1 and 2 are code-complete and verified. Only the real-phone step is
outstanding, and it is blocked on Meta, not on us.**

Phase 2 (the dose loop) passes 42/42 checks against the live database with the
sender stubbed: materialisation idempotency, the taken path, the missed path
(follow-up then caretaker alert), the late-reply reclassification, refusal of
illegal transitions, no re-send across restarts, stale-dose suppression, a
button tap driven through the real webhook, and "abhi nahi" correctly *not*
acting as a snooze.

**What is genuinely unverified:** that a message leaves Meta and lands on a
phone. Everything up to the moment of transmission is proven.

## Next steps

1. **Meta account** (blocked, team is on it). Capture the literal error text.
   Do NOT register your own number as the sender - Meta issues a free test
   number, and a number that already has WhatsApp can never be a sender.
2. When the token lands, fill the four WHATSAPP_* values in `.env`, then:
   `python scripts/send_test.py <number>` and tap a button. That closes the
   Phase 1 gate. Then set a dose two minutes out and walk away to close
   Phase 2's.
3. Submit the four templates from §10 and **tell Claude which language code you
   submitted under** - it goes in `WHATSAPP_TEMPLATE_LANG`, and a mismatch
   fails silently.
4. `DASHSCOPE_API_KEY` is still empty. Phase 3's `interpret` and `knowledge`
   need it to run; `guardrails` and `i18n` do not and can be finished and
   tested without it. **This is now the only other external blocker** — and it
   is independent of Meta, so it can be done in parallel.
5. Voice needs nothing from anyone: no account, no card, no key.

## Environment / setup

**Toolchain on the current dev machine (Windows 11):** Python 3.14.4,
Node 24.18.0, npm 11.16.0, git 2.54.0. **`make` is not installed.**

**Commands** — the Makefile is canonical and is what runs on the ECS box in
Phase 8. On Windows use the PowerShell shims, which do the same thing:

| Purpose | Makefile | Windows |
|---|---|---|
| install deps | `make install` | `.\install.ps1` |
| run both processes | `make dev` | `.\dev.ps1` |
| tests | `make test` | `.\test.ps1` |
| seed demo data | `make seed` | `.\seed.ps1` |

Backend on :8000 (health at `/api/health`), frontend on :3000.

**Env vars** — names only, in `.env.example`. `.env` is gitignored. All five of
`DATABASE_URL`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_VERIFY_TOKEN`, `DASHSCOPE_API_KEY` are currently **unset**;
`/api/health` lists exactly which are missing at any time.

**Accounts still to create:** Meta Developer + WABA (blocked), DashScope.
Supabase is done. **No voice account is needed any more** — see the TTS swap
in the decisions log.

**Git / GitHub:** remote is `https://github.com/abzakir/MedNuskha`, branch
`main`. Phase 0 is pushed (`a163ac9`). **Standing instruction from the team:
commit and push at the end of every phase** — one commit per phase, message in
the `feat(scope): ...` form from §12. `.gitattributes` normalises the repo to
LF (with `.ps1` kept CRLF) because the backend ships to an Ubuntu ECS box in
Phase 8, where a CRLF Makefile breaks.

**Team-facing doc:** `MedNuskha_Setup_Guide.pdf` at the repo root is the complete walkthrough of every external task — Meta WhatsApp, Supabase, DashScope, ngrok, Google Cloud TTS, ECS + Vercel deploy — plus a troubleshooting table and a tick-off checklist. Hand it to any teammate doing account setup. Regenerate it if the steps change.

**WhatsApp templates:** none submitted yet. All four are pending action.

## Gotchas discovered

- **WeasyPrint installs on Windows but will not import.** `import weasyprint`
  raises `OSError: cannot load library 'libgobject-2.0-0'` — it needs the GTK3
  runtime, which pip does not provide. **This blocks Phase 6 on Windows.** Two
  ways out: install the GTK3 Runtime for Windows on the dev machine, or accept
  that PDFs only generate on the Ubuntu ECS box (Phase 8), where `apt` pulls
  Pango in as a normal dependency. Decide before Phase 6 starts, not during it.
  Nothing imports weasyprint yet, so this is inert until then.
- **Everything else installs and imports cleanly on Python 3.14**, including the
  two that were most at risk: `faster-whisper 1.2.1` (with `ctranslate2 4.8.1`
  cp314 wheels) and `google-cloud-texttospeech 2.37.0`. The Day-3 wheel risk is
  effectively gone.
- **`shadcn init -d` fails** with `Validation failed: - tailwind: Required`.
  `shadcn@2 init -d -b zinc` works — the base colour must be passed explicitly.
  Without `-d` the CLI prompts interactively and hangs in a non-TTY.
- **`create-next-app` initialises its own git repo inside `frontend/`.** It was
  deleted so the project has one repo at the root, not a nested one. If anyone
  re-scaffolds the frontend, delete `frontend/.git` again.
- **Git Bash heredocs on this machine collapse `\\` to `\`.** A Python docstring
  written that way produces a `SyntaxWarning: invalid escape sequence`. Use the
  Write tool, or avoid backslashes, for Python files.
- **Supabase's transaction-mode pooler (port 6543) cannot use server-side
  prepared statements.** `db.py` already passes `prepare_threshold: None` and
  `pool_pre_ping=True` (free-tier projects pause after inactivity and drop idle
  connections). Do not remove either.
- **Supabase hands out `postgresql://` URLs**, which SQLAlchemy maps to psycopg2
  — a driver we do not install. `settings.sqlalchemy_url` rewrites the scheme to
  `postgresql+psycopg://`. Always use `settings.sqlalchemy_url`, never
  `settings.database_url`, to build an engine.

- **Meta Cloud API shapes, verified from Meta's own docs on 2026-08-22** (do
  not re-derive these from memory):
  - Send: `POST https://graph.facebook.com/{version}/{PHONE_NUMBER_ID}/messages`
    with `Authorization: Bearer` + `Content-Type: application/json`.
  - Template body: `{"messaging_product":"whatsapp","to":"...","type":"template",
    "template":{"name":..., "language":{"code":...}, "components":[...]}}`.
  - Quick-reply button component:
    `{"type":"button","sub_type":"quick_reply","index":0,
      "parameters":[{"type":"payload","payload":"TAKEN:<dose_id>"}]}`.
    Max 3 dynamic button payloads per template.
  - Send response: `messages[0].id` is the `wamid...` we store as
    `wa_message_id`.
  - **Media download is two steps and the URL expires in 5 minutes:**
    `GET /{version}/{MEDIA_ID}` returns `url`, `mime_type`, `sha256`,
    `file_size`, `id`; then GET that url **with the Bearer token attached** —
    omitting it fails.
  - Media upload: `POST /{version}/{PHONE_NUMBER_ID}/media`, multipart, fields
    `messaging_product=whatsapp`, `type`, `file`. Returns `{"id": ...}`, and
    media ids expire after 30 days.
  - Audio must be **audio/ogg with OPUS codec, mono** — plain ogg is rejected.
    16 MB cap. This matches invariant 7 exactly.
- **The current Graph API version is v26.0** (released 2026-07-29). AGENTS.md
  §13 pins `WHATSAPP_API_VERSION=v23.0` (2025-05-29), which is still supported
  and was left as the default — it is an env var, so changing it is a one-line
  edit, not a code change. Flagged rather than silently bumped.
- **You do not need your own phone number to send.** Meta issues a free test
  number when the WhatsApp product is added; your own numbers are only ever
  *recipients* on the 5-number whitelist. Trying to register a number that
  already has WhatsApp on it as the sender always fails.

- **`rowcount` is -1 for a multi-row `ON CONFLICT` insert** under psycopg.
  `materialise_doses` uses `RETURNING id` and counts the rows instead. The
  idempotency was always correct; only the logged count was wrong, which is
  exactly the kind of thing that sends someone debugging the wrong problem.
- **Meta rejects an empty template parameter**, and also newlines, tabs and
  runs of four or more spaces. `ticker._clean_var` sanitises every variable and
  substitutes a non-empty fallback - otherwise a medicine with no confirmed
  food rule would fail the send at the moment a real dose was due.
- **Git Bash heredocs are unreliable on this machine for anything long** -
  they silently truncate or mangle backslashes. Write Python patch scripts to
  a file and run them, or use the editor tools directly.
- **A button payload naming a non-existent dose used to lose the whole
  message.** `message_log.dose_event_id` is a foreign key, so the insert failed
  and the handler misread that as a duplicate. Duplicates and real integrity
  failures are now told apart, and an unknown dose id stores the payload with a
  null link rather than dropping the row.

- **edge-tts returns MP3, and WhatsApp needs OGG/Opus mono** (invariant 7).
  PyAV does the conversion in about 0.2s and is already installed as a
  faster-whisper dependency, so **no ffmpeg binary is needed** on the dev
  machine or the ECS box. Verified end to end on real Urdu text.

## Decisions log

### 2026-08-22 — Session 4 (TTS stack swap)

**Reason:** the team reported Google Cloud TTS wanting a card on file (~$10),
and asked for a free alternative. §6 forbids swapping the voice stack silently,
so alternatives were tested and the choice was put to the team, who approved.

**Swap: Google Cloud TTS -> `edge-tts`, voice `ur-PK-UzmaNeural`.**

Not a downgrade. `edge-tts` reaches Microsoft's neural voices — the same ones
Azure sells — with **no account, no card and no API key**. Two Pakistani Urdu
voices exist: `ur-PK-UzmaNeural` (female, chosen — a warmer, more caregiver-like
read, which fits §11's "never scolds" tone) and `ur-PK-AsadNeural` (male).

**Proven before proposing, not after:** real Urdu text through the full
pipeline — synth 1.8s, MP3 -> OGG/Opus mono 48kHz in 0.2s via PyAV, container
and codec verified by probing the output file. Samples were sent to the team to
judge the voice by ear.

**Why this is better than what it replaced:**

- No credentials to create, distribute to teammates, or install on the ECS box.
  One fewer secret, and one fewer thing to misconfigure on Day 4.
- Smaller dependency tree: `google-cloud-texttospeech` drags in grpc, protobuf
  and google-auth. `edge-tts` is tiny.
- PyAV was already present via faster-whisper, so **no ffmpeg binary** is
  required anywhere.
- Synthesis latency is irrelevant regardless: §3.4 pre-generates voice notes
  when a schedule is confirmed, so nothing is synthesised in the reminder path.

**The honest caveat, recorded so nobody is surprised later:** edge-tts uses the
endpoint behind Edge's read-aloud feature. It is not a documented public API.
Fine for a hackathon; if this outlives the demo, Azure Speech's F0 tier has the
identical voices free for 500k characters a month. It also needs internet — if
the venue has none, §6's Piper fallback still stands.

**Updated everywhere it is named**, not just in code: AGENTS.md §6 table and
voice notes, §13 env vars, §14 Phase 5 prompt / kill switch / "your turn";
`requirements.txt`; `.env.example`; `config.py`; and
`MedNuskha_Setup_Guide.pdf` §5, which previously told the team to create a
Google Cloud service account.

**New env var:** `TTS_VOICE` (default `ur-PK-UzmaNeural`).
**Removed:** `GOOGLE_APPLICATION_CREDENTIALS`.

### 2026-08-22 — Session 3 (Phases 1 and 2)

**Done:** Phase 1 (whatsapp client, parser, webhook, send_test) and Phase 2
(state machine, ticker) written and verified — 26/26 and 42/42 against the live
database, with outbound sends captured rather than transmitted.

**Key decisions:**

- **Claim-before-send.** `mark_sent` moves SCHEDULED -> SENT *before* the
  reminder is transmitted. A crash mid-send therefore leaves the dose SENT and
  the restart never re-sends it (invariant 5). The trade is that a failed send
  leaves a dose marked SENT with nothing delivered; the follow-up covers that,
  and the failure is in `message_log`. A duplicate reminder to a 68-year-old is
  worse than a late one.
- **A Postgres advisory lock guards the scheduler**, not just a module flag.
  A flag only protects one process; the lock stops a second uvicorn worker, or
  a teammate running `dev.ps1` against the same Supabase project, from firing
  every reminder twice. It is released automatically if the process dies.
- **Stale doses are marked MISSED, never reminded.** If the server was down
  past the escalation window, waking up and blasting a burst of old reminders
  at an elderly patient would be worse than useless.
- **"Abhi nahi" is not a snooze.** It records the reply and leaves the dose
  open, so the follow-up and the caretaker escalation still run. Snoozing
  beyond it is explicitly out of scope (§4), and the caretaker should still
  learn the dose was not taken.
- **Illegal transitions are refused and logged**, not silently applied. This is
  what stops a late webhook retry from dragging a TAKEN dose back into
  REMINDED_AGAIN.
- **New env var: `WHATSAPP_TEMPLATE_LANG`** (default `en`), added to
  `.env.example`. §13 has no such name, but the language code a template was
  submitted under must match at send time or the send fails silently, and
  hardcoding it would be worse. **The team must set this to whatever they
  actually submitted.**
- **`_record_later` deliberately lives in webhook.py, not state_machine.py.**
  It touches `response_text` and `reason` but never `state`, and §8 reserves
  the state machine for transitions only.

**Not done / not verified:** any real transmission. Also `reports/` and the
daily report job were left alone — Phase 6 owns them, and referencing a module
that does not exist yet would have broken the scheduler at import time.

**Before touching this area next:** `state_machine.ALLOWED` is the single
source of truth for what transitions are legal. Add a state there before using
it anywhere else, or the transition will be silently refused.

### 2026-08-22 — Session 2 (Phase 1, paused)

**Done:** Supabase connected and verified (Postgres 17.6, Seoul, session
pooler). `init_db()` created all 11 tables and both unique constraints —
confirmed by querying `information_schema`, not assumed. Meta's Cloud API
reference fetched and the exact request/webhook/media shapes recorded in
Gotchas before writing any client code, per §14 Phase 1.

**Blocker:** the team hit a problem creating the Meta Developer/Business
account. Exact error not yet captured. Phase 1 paused rather than written
blind — there is no token to test against.

**Provider alternatives evaluated** (in case Meta stays blocked):

- **Twilio WhatsApp Sandbox** — Twilio's docs state no WhatsApp Business
  Account or registered sender is needed, so it bypasses Meta entirely. Also
  removes the template-approval wait: a participant sends `join <code>`, which
  opens a 24-hour free-form window, and the demo script keeps that window open
  because the patient keeps replying. Costs: shared Twilio-branded US number,
  participants re-join every 3 days, adds the `twilio` package, and **no tap
  buttons** without going through Content Template approval.
- **whatsapp-web.js / Baileys on the spare number** — no approvals, no
  whitelist, no window, native voice notes. But it violates WhatsApp's terms,
  the number can be banned, it needs a Node sidecar beside the Python backend,
  and it has no buttons either.
- **Telegram** — trivially easy, but WhatsApp is the product thesis (§3.1).
  Emergency only.

**Decision:** retry Meta with the free test number. Chosen by the team over
switching provider, since Meta direct is the only option that keeps tap buttons
and therefore invariant 2 intact.

**The invariant at stake if we ever switch:** both fallbacks lose tap buttons,
which breaks **invariant 2** (the dose id travels in the button payload; never
infer the dose from timing). Any switch must carry a written exception: match a
reply to the patient's single dose in `AWAITING_REPLY`/`REMINDED_AGAIN`, and
ask which one when two are open. Do not let that slip in silently.

**Cost of switching is low by design:** invariant 6 confines every outbound
call to `whatsapp/client.py`, so a provider change is one module, not a
rewrite. That was worth the discipline.

**Before touching this area next:** the API shapes in Gotchas were fetched from
Meta on 2026-08-22 — reuse them rather than re-fetching, but do re-verify if
more than a few days pass.

### 2026-08-22 — Session 1 (Phase 0)

**Done:** full repo skeleton per §7; `requirements.txt`; `.env.example` from
§13; `.gitignore`; Makefile + PowerShell shims; real `config.py`, `db.py`,
`models.py`, `main.py`; every other backend module as a signature-only stub;
Next.js 14.2.35 + Tailwind 3.4 + shadcn/ui scaffold with `lib/api.ts` and a
stub page at `/`; `SCHEMA.md`; this log. Gate verified end to end.

**Key decisions:**

- **Python 3.14, not the 3.11 in §6.** 3.11 was not installed and 3.14 was;
  the team chose to proceed on 3.14 rather than spend setup time. Vindicated —
  every dependency installed, and only WeasyPrint fails to import, for a reason
  unrelated to the Python version (missing GTK, see Gotchas). *§6 stack table
  should be read as "Python 3.11+" until someone updates it.*
- **Makefile kept AND PowerShell shims added.** `make` is not on the dev
  machine but the Makefile is what runs on Ubuntu in Phase 8, so both exist and
  do the same three things. No dependency added.
- **`schedule.end_date` is INCLUSIVE.** §8 writes `end_date = start_date +
  duration_days`, which yields an 8th day of doses for a 7-day course. Stored
  as `start_date + duration_days - 1` instead: a 7-day course starting
  2026-08-22 ends 2026-08-28, giving exactly `duration_days × len(dose_times)`
  doses. This is what "7-day course" means to a caretaker and what reads
  correctly on the doctor PDF. **Phase 2's materialiser and Phase 6's course-end
  check must both treat it as inclusive** (`end_date < today` means the course
  is over).
- **11 tables, not 9.** §8's prose says "Eleven tables" and lists eleven; the
  Phase 0 prompt in §14 says "all nine tables from §8". Built all eleven, since
  the named list is unambiguous and `medicine_reference` and `report` are both
  required by later phases.
- **Multiple caretakers per patient is handled by `family`, not a join table.**
  §4.10 wants many caretakers on one patient; §8 fixes the table count at
  eleven and puts `relation` on `caretaker`. So caretakers and patients both
  belong to a family and every caretaker in a family sees that family's
  patients. No twelfth table invented (§4: delete abstractions for use cases
  that do not exist).
- **`patient_id` denormalised onto `dose_event`.** The dashboard polls today's
  doses every 5 seconds; without it that is a three-table join on every poll.
- **Stubs raise `NotImplementedError("Phase N — …")` rather than `pass`.** §0
  forbids placeholder code, §14 Phase 0 explicitly asks for signature-only
  modules. Raising satisfies both: the contract is frozen and callable, and
  nothing can silently return a wrong answer.
- **`reports/caretaker_pdf.py` was NOT created.** §7's file layout does not list
  it, and §0 says stay inside that layout — but Phase 6 explicitly requires it.
  It gets created in Phase 6. Flagging so nobody thinks it was forgotten.
- **`GET /api/health` reports rather than asserts.** The app boots and returns
  200 with an empty `DATABASE_URL`, listing what is missing, instead of
  crashing. Without this the Phase 0 gate could not be verified before Supabase
  existed, and a paused Supabase project would take the whole demo down at the
  wrong moment.
- **shadcn components pre-added:** `button`, `card`, `table`, `badge` (the four
  §14 Phase 4 names), plus `input`, `label`, `select` for the add-patient and
  add-medicine forms. Adding them now means Phase 4 needs no network.

**Blockers hit:** none that stopped work. `shadcn init -d` and the WeasyPrint
import both failed and are recorded in Gotchas with their resolutions.

**Before touching this area next:** `models.py` is **frozen**. There is no
Alembic — `create_all` only creates missing tables, it never alters one. If a
column genuinely must change after the first real boot, drop that table in
Supabase by hand and let it recreate, and log why.
