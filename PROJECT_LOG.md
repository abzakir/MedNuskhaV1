# MedNuskha — Project Log

> Read `AGENTS.md` first, then this file. Between them a session with no memory
> can pick the project up exactly where it was left.

---

## Current state

**The product works end to end on real infrastructure.** A caretaker signs up
on the website, adds a family member and their medicines, and the patient gets
WhatsApp reminders at every dose. Replies in Urdu, Roman Urdu or English —
typed or spoken — are understood and drive the dose state. Silence escalates to
the caretaker. Proven on a real phone, not in theory.

### What is running

Four processes. `.\dev.ps1` starts all of them.

| Process | Port | What it is |
|---|---|---|
| **Dashboard** | 3000 | Next.js 14, the caretaker's website |
| **Backend** | 8000 | FastAPI — API, scheduler, agent, webhook |
| **WhatsApp bridge** | 3001 | Node + Baileys, owns the WhatsApp socket |
| Supabase | — | Postgres 17, 11 tables, hosted |

`GET /api/health` reports the state of all of it in one call: database,
scheduler, WhatsApp connection and how many AI keys are alive.

### Built and verified

| Phase | What | Status |
|---|---|---|
| 0 | Repo, schema, config | done |
| 1 | WhatsApp transport | done — real messages on a real phone |
| 2 | Dose loop: remind, follow up, escalate | done — 42/42 |
| 3 | Agent: understand replies, guardrails | done — 38/38 + 57 unit tests |
| 4 | Website: sign-up, patients, medicines | done — 42/42 |
| — | Caretaker commands over WhatsApp | done — 11/11 (added at team request) |
| 5 | Voice notes attached to reminders | **not built** |
| 6 | The two PDF reports | done — 58/58 + 20/20 over HTTP + 25 unit tests |
| 7 | Prescription OCR (stretch) | not built |
| 8 | Deploy to ECS + Vercel | not built |

Voice **understanding** already works — an inbound voice note is transcribed
and acted on. What is missing from Phase 5 is the outbound half: pre-generating
an Urdu voice note and attaching it to each reminder. The TTS pipeline itself is
proven (see the decisions log); it is not yet wired into the reminder path.

### Test inventory

```
pytest backend/tests/                    82 unit tests, no services needed
scripts/verify/                          ~280 integration checks, live services
```

`scripts/verify/README.md` says what each one proves and how to run it.

### Known gaps

- **No voice note on reminders yet** (Phase 5). Everything else in the core
  product is built.
- **`SUPABASE_SERVICE_KEY` is not set**, so reports are generated and served
  but **not archived** to Supabase Storage. Nothing is broken by this — the
  share link rebuilds the PDF from the database — but Phase 5's voice notes
  will need the same key, so it is worth adding. See `.env.example`.
- **Buttons do not exist.** WhatsApp removed them for non-official clients, so
  reply options are numbered text. Invariant 2's replacement is documented in
  the decisions log and pinned by `test_state_machine.py`.
- **Baileys is a release candidate** (7.0.0-rc14). Deliberate: 6.17.16 cannot
  resolve LID senders, which means it cannot tell who replied.
- **`DEV_AUTH_BYPASS=true`** in the local `.env`. It must be false in production.
- **A demo patient is sitting in the database** — "Zubaida Bibi (demo)" on
  920000000197, with a full 14 days of history, seeded so the dashboard report
  buttons have something real to render. Delete it when you are done:
  `backend\.venv\Scripts\python.exe scripts\verify\purge_patient.py 920000000197`

---

## Current phase

**Phase 5 (voice notes on reminders) is the only piece of the core product
left.** Phase 6 landed this session. Nothing external is blocking Phase 5 —
every account and key is in place, except the Supabase secret key it shares
with report archiving.

## Next steps

1. **Click the two report buttons on the dashboard yourself.** Everything below
   them is verified — the endpoint they call is 20/20 over real HTTP — but the
   click itself was never performed, because the dashboard needs a Supabase
   sign-in and this session would not sign in on anyone's behalf. Open
   "Zubaida Bibi (demo)", which has 14 days of history waiting.
2. **Add `SUPABASE_SERVICE_KEY` to `.env`** (Project Settings → API keys → the
   `sb_secret_` one). Reports work without it; they are just rebuilt on each
   open rather than archived. Phase 5 needs the same key to upload voice notes,
   so this unblocks both. `verify_reports.py` reports it as a warning until it
   is set.
3. **Phase 5 — outbound voice.** Pre-generate one OGG/Opus file per unique dose
   text when a schedule is confirmed, store it in Supabase Storage, attach it to
   the reminder. Never synthesise in the reminder path. Caching by
   `(medicine, dose_time)` matters — one file per unique sentence, not per dose.
   `reports/storage.py` already has the upload/bucket plumbing to copy.
4. **Phase 8 — deploy.** ECS for the backend and bridge, Vercel for the
   dashboard. The PDF stack no longer needs system packages — that was the
   point of dropping WeasyPrint. Set `DEV_AUTH_BYPASS=false`, and set
   `NEXT_PUBLIC_API_BASE` to the real host or every report share link sent over
   WhatsApp will point at `localhost:8000`.
5. Phase 7 (prescription OCR) is the stretch and should only be attempted if
   1–4 are finished.

---

## Environment / setup

### Starting it

```powershell
.\dev.ps1        # everything: bridge, backend, dashboard
.\bridge.ps1     # the bridge alone, when you need to see the QR code
.\test.ps1       # unit tests
```

`make dev` / `make bridge` / `make test` do the same on Linux, which is what
runs on the ECS box in Phase 8.

### Signing in

The dashboard is at **http://localhost:3000**. Sign-up works immediately —
email confirmation is switched off in Supabase, and Google sign-in is
deliberately not enabled (the button hides itself when a provider is off).

### Credentials — all present and verified

| Thing | State |
|---|---|
| Supabase Postgres + Storage | working, 11 tables |
| Supabase Auth (email/password) | working, autoconfirm on |
| WhatsApp via Baileys | linked to **923200268481**, session in `whatsapp-bridge/auth_info/` |
| Groq | 3 keys pooled and rotating, all verified |
| edge-tts (Urdu voice) | no account needed |
| faster-whisper (local ASR) | model cached |
| DashScope / Alibaba | not yet — drops into the same rotation when it arrives |

Everything lives in `.env` at the repo root, which is gitignored. `.env.example`
documents every name. **`whatsapp-bridge/auth_info/` is a real WhatsApp login —
never commit it, never share it.**

### If WhatsApp stops working

1. `curl http://localhost:3001/status` — `connected` is what you want.
2. `qr` means it needs re-pairing: run `.\bridge.ps1` and scan.
3. `logged_out` means the device was unlinked. Delete
   `whatsapp-bridge/auth_info/` and pair again.
4. Replies arriving but nothing happening? Check the bridge is posting to
   `/webhook/<WEBHOOK_SECRET>` — without the secret the backend answers 403 and
   the message is silently lost. `dev.ps1` handles this automatically.

### Git

Remote is `https://github.com/abzakir/MedNuskha`, branch `main`. **Commit and
push at the end of every phase**, one commit per phase, `feat(scope): ...` per
§12. Claude is not added as a co-author, at the team's request.

---

## Gotchas discovered

- **WeasyPrint installed on Windows but would not import**, and has now been
  **removed** — `import weasyprint` raised
  `OSError: cannot load library 'libgobject-2.0-0'`, because it needs the GTK3
  runtime and pip does not provide it. Replaced with fpdf2 in Session 8; see
  that entry for why, and AGENTS.md §6 for the note that replaced this one.
- **fpdf2 renders Urdu only with `set_text_shaping(True)` AND uharfbuzz
  installed.** Miss either and Arabic-script letters do not join and come out
  left-to-right — unreadable, but it still produces a valid-looking PDF, so
  nothing fails loudly. `reports/pdf.py` sets both up; do not "simplify" it.
- **Noto Naskh Arabic has no Latin glyphs.** A mixed line like
  `Panadol لے لی ہے` — which is exactly what a verbatim quote looks like —
  cannot be rendered from it alone. The fix is Noto Sans as the main font with
  Naskh registered via `set_fallback_fonts()`. **Fallback does not work from a
  core font**: Helvetica is Latin-1 and raises `FPDFUnicodeEncodingException`
  before fallback can engage, so the main font must itself be a Unicode TTF.
- **You cannot grep a fpdf2 PDF for its own text.** The bundled TTFs are
  subset, so the content stream holds glyph ids, not characters — a byte search
  finds nothing whether or not the sentence is on the page. Turning compression
  off does not help. Use a real extractor (`pypdfium2`) or you will "fix" a
  disclaimer that was there all along.
- **The Supabase publishable key cannot write to Storage.** Verified
  2026-08-23: it lists buckets fine, but both bucket creation and upload come
  back `new row violates row-level security policy`. Uploading needs the
  `sb_secret_` key. This applies to Phase 5's voice notes too.
- **`dev.ps1` runs uvicorn without `--reload`.** A backend started before a
  code change silently 404s on new routes, which looks exactly like a routing
  bug. Restart it, or run a second instance on another port to test against.
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

- **`WHISPER_MODEL=base` is unsafe for Urdu. Use `small`.** Measured
  2026-08-22 on synthesised Urdu of the exact phrases patients send: `base`
  transcribed **"ابھی نہیں" (*abhi nahi*, "not now") as "اب ہی" (*ab hi*,
  "right now")** — a meaning inversion on a dose reply. `small` returns it
  exactly. AGENTS.md §6 originally assumed short utterances were the easy case
  for Urdu ASR; the opposite is true. Long phrases ("seene mein dard ho raha
  hai", "goli khatam ho gayi hai") come back verbatim on both models, while
  two-word replies are where `base` fails.
  Cost of the upgrade: ~0.5x realtime instead of ~1.1x on CPU, so about 5s for
  a 2s clip. Irrelevant — ASR runs in a background task, never on the webhook
  path.
- **Transcription does not need to be perfect, and must not be treated as if it
  is.** `small` still returns "لیلی ہے" for "لے لی ہے" — spacing and spelling
  drift. That is fine because Qwen reads the transcript, not a regex, and
  "leli hai" is still unmistakably "I took it" to a language model. It is also
  exactly why §11 sets a 0.6 confidence floor: on a garbled transcript the
  agent asks one short clarifying question rather than guessing.

- **`reasoning_effort: "none"` is required for qwen3.6-27b on Groq.** Without
  it every reply is prefixed with a `<think>` block that would reach the
  patient and break JSON parsing. `reasoning_format: "hidden"` returns an
  EMPTY string - worse. Verified live.
- **Deleting a caretaker fails while a `medicine_reference` row names them** in
  `confirmed_by`. Fine in production (caretakers are not deleted), but any
  cleanup script must remove reference rows first.
- **A `Patient` object detached with `expunge()` after later commits is
  expired** and raises `DetachedInstanceError` on attribute access. Call
  `refresh()` immediately before `expunge()`.

- **Never run `npm run build` while `npm run dev` is running.** They share
  `frontend/.next` and write incompatible layouts into it. The dev server then
  fails with `Cannot find module './vendor-chunks/@supabase.js'`, which reads
  like a missing dependency and is not. Fix: stop dev, `rm -rf frontend/.next`,
  start dev. `dev.ps1` now detects a leftover production build (`.next/BUILD_ID`
  only exists after `next build`) and clears it automatically.

- **A MISSED dose must not compete with one that is awaiting a reply.**
  Observed on a real phone 2026-08-23: a patient with one dose in
  AWAITING_REPLY and one MISSED earlier that day had *every* reply answered
  with "samajh nahi aaya". `resolve_dose` counted both as open, called it
  ambiguous, and refused to guess - correctly by its own rule, but the rule was
  wrong. Missed doses accumulate, so comprehension degraded by the day.
  Fixed: doses in SENT / AWAITING_REPLY / REMINDED_AGAIN take priority, and
  MISSED ones are only candidates when nothing else is open (and only within
  12 hours, for a late confirmation). Pinned by tests 4, 5 and 6 in
  `test_state_machine.py`.
- **WhatsApp sends `protocolMessage` and friends constantly.** They are read
  receipts, ephemeral-timer changes and revokes - not anything a human typed.
  The bridge was forwarding them, so the activity log showed the patient
  saying "other" every few minutes. The bridge now drops
  `protocolMessage`, `senderKeyDistributionMessage`, `messageContextInfo`,
  `reactionMessage`, `pollUpdateMessage` and `keepInChatMessage`.

## Decisions log

### 2026-08-23 — Session 8 (Phase 6: the two reports, and a wording fix)

**Done:** Phase 6 in full — `reports/data.py`, `pdf.py`, `doctor_pdf.py`,
`caretaker_pdf.py`, `storage.py`, `service.py`; the daily course-end job in
`ticker.py`; `GET /api/patients/:id/report.pdf` and the share link
`GET /api/reports/:id.pdf`; both buttons on the medicine card. 58/58 against
the live database, 20/20 over real HTTP, 25 new unit tests (82 total).

**The PDF stack changed: WeasyPrint → fpdf2 + uharfbuzz.** Put to the team
with both options costed, and chosen by them. WeasyPrint could not import on
Windows at all (no GTK), so Phase 6 was unverifiable locally. The alternative
was `winget install tschoonj.GTKForWindows` on every Windows machine plus Pango
and Noto packages on ECS. fpdf2 is pure pip and behaves identically on both.
Proven before proposing, per Session 4's precedent: real Urdu was rendered and
read back off the page before the swap was offered. §6, its new PDF note,
`requirements.txt` and the Phase 6 prompt are all updated. `jinja2` went too —
it was only there for WeasyPrint's HTML templating and nothing imported it.

**Fonts are committed to the repo**, at `backend/app/reports/fonts/`, ~1.7MB
of OFL-licensed Noto. Not a casual choice — Windows has Arial with full Urdu
coverage but it is not redistributable, and a bare Ubuntu box has neither.
Bundling is the only way the ECS output matches what was signed off here.

**Key decisions:**

- **Both reports read one `data.py`.** They describe the same course from two
  angles and are generated a second apart; if each ran its own queries they
  could disagree about how many doses were taken, and a caretaker holding both
  would have no way to know which was right.
- **Doses awaiting a reply are excluded from adherence, never counted as
  missed.** Otherwise the same fortnight reports 82% at night and 58% at
  breakfast, purely because the evening dose has not been answered yet. Pinned
  by four unit tests, because it is the kind of thing a later "simplification"
  would quietly undo.
- **The caretaker report contains no percentage at all.** §14 asks for "a
  caring update, not a spreadsheet". "11 of 14" is a fact a person can hold;
  "78.6% adherence" is a metric about their mother. A test asserts no `%`
  survives into that PDF.
- **The share link points at our own API, not at Supabase Storage.** A
  WhatsApp link cannot carry a Bearer token, and §8 froze the `report` table
  with nowhere to put a share token — so the token is *derived*: an HMAC of
  the report id under `WEBHOOK_SECRET`. Stateless, unguessable, no schema
  change. A wrong token returns 404 rather than 403, so a guess cannot confirm
  a report exists.
- **Archiving is best-effort, and the endpoint regenerates.** Every number in
  the document comes from Postgres, so a rebuilt PDF says exactly what the
  archived one said. That is what lets the whole feature work today without
  the secret key.
- **The daily job is idempotent through the `report` rows themselves**, not a
  flag. Generation happens once even if the WhatsApp send fails — the right
  way round, since a caretaker who missed the message can still open the report
  from the dashboard, whereas duplicate PDFs arriving every morning is noise.

**Also fixed, at the team's request:** not understanding a message used to send
a fixed string — the patient got "samajh nahi aaya" verbatim every time and the
caretaker got "send help" however close their message was to a real command.
Both paths now spend the whole Groq pool on wording one short reply and only
fall back to the canned string when every key is down. The model chooses words,
never actions: dispatch has already decided nothing matched, and the draft
still goes through guardrails. `llm.try_chat()` is the shared piece.
Live result: "wo band kar do na" now points at `pause`, "ammi ka kya haal hai"
at `status`.

**Not done:** the dashboard buttons were never actually clicked. The endpoint
behind them is verified over real HTTP and the frontend type-checks, but the
dashboard requires a Supabase sign-in and this session would not sign in on
anyone's behalf. "Zubaida Bibi (demo)" is seeded with 14 days of history for
exactly that click — see Next steps.

**Before touching this area next:** `reports/data.py` is the only module that
decides what a number means. Change adherence, streaks or "hardest time" there
and both PDFs follow; change either PDF and you have made them disagree.

### 2026-08-23 — Session 7 (caretaker commands, and this handover)

**Done:** the caretaker can now run the system from WhatsApp - status, pause,
resume, help - by text or voice note, in Urdu script, Roman Urdu or English.
`agent/caretaker.py`, wired through the same webhook the patient uses. 11/11
verified against the live database.

**Key decisions:**

- **Adding or editing a medicine is deliberately NOT a WhatsApp command.** It
  needs the confirmation screen. A medicine created from a voice note would
  bypass precisely the human check invariant 3 exists to enforce, and that is
  the one place in this product where a plausible hallucination becomes a
  patient-safety problem rather than a bug.
- **The clinical check runs BEFORE the pause check.** "Should I stop her
  medicine?" contains "stop"; reading it as a pause command would be a quietly
  dangerous misread. Clinical questions are refused whoever asks - being the
  carer does not make the agent a doctor.
- **Writing the tests found a real gap.** The dose-change patterns only knew
  "take", so "can I GIVE her two tablets" - the only way a caretaker would
  phrase it - passed straight through. Every combination of can/should/may/shall
  with i/we/she/he/they now matches.
- **Verification scripts moved into the repo** at `scripts/verify/`. They lived
  in a scratch directory and would have been lost the moment context was
  cleared - roughly 200 integration checks representing how every phase was
  actually proven. Not in the §7 layout; the alternative was losing them.
- **PROJECT_LOG's live sections were rewritten** rather than appended to. They
  had grown by accretion across seven sessions and no longer described the
  system as it stands. §1 says these three sections are overwritten each
  session; this is that, done properly.

**State at handover:** phases 0-4 complete and verified, plus caretaker
commands. Phases 5 (outbound voice notes) and 6 (the two PDFs) are what remain
of the core product. Nothing external is blocking either - every account, key
and credential is in place and verified working.


### 2026-08-23 — Session 6 (Phase 3: the agent)

**Done:** `interpret`, `respond`, `guardrails`, `knowledge`, `llm`, `voice/asr`,
`i18n/strings`, and `tests/test_guardrails.py`. Wired into the webhook so a
typed or spoken reply now acts. 38/38 agent checks against live Groq and the
live database; 32/32 guardrail tests.

**Invariant 2's replacement is implemented and tested.** With buttons gone,
`interpret.resolve_dose` resolves a reply against the doses actually awaiting
an answer: an explicit payload wins if present, one open dose is unambiguous,
several open doses are disambiguated by the medicine name in the reply, and
anything still ambiguous returns `unclear` so the agent asks instead of
guessing. Verified: with two doses open and a bare "haan le li", **neither**
dose is marked taken and the patient is asked which medicine.

**Key decisions:**

- **Fast paths before the model.** "haan", "abhi nahi", "1", "2", STOP and the
  emergency keywords are matched with regexes first. That saves a model call on
  the most common reply in the system, works when every key is rate-limited,
  and removes the model from the emergency path entirely.
- **Keyword matching is the authority on emergencies, not the model.** If the
  emergency regex fires, the intent is `emergency` regardless of what the model
  said. A model deciding chest pain is routine is not a failure mode we accept.
- **A short-message guard on the keyword matcher.** "le li" only counts as a
  confirmation in a message of four words or fewer, because inside a longer
  sentence it may well be "abhi tak nahi le li".
- **Guardrails run on the OUTBOUND text, not the prompt.** A system prompt can
  be talked around; a regex over the final message cannot. Deliberately
  conservative: a false block costs one safe-but-unhelpful message plus a
  caretaker alert, a false pass costs an elderly patient acting on invented
  medical advice.
- **`test_17` caught a real hole.** The dose-change rule matched "take two
  tablets" but not "**took** two tablets", so a hypothetical framing passed.
  Every tense is now covered - that framing is exactly how a model gets talked
  around its instructions.
- **Invariant 9 is enforced by structure, not discipline.** There is no code
  path from a patient's question to a live model call about a medicine.
  `_on_question` calls `get_confirmed()` and, on None, sends the "no confirmed
  information" line and alerts the caretaker. `get_any()` exists for the
  dashboard and is documented as never for the reply path.
- **ASR falls back automatically.** Groq `whisper-large-v3` first, local
  `faster-whisper` when the pool is down. A failed transcription returns "",
  which becomes `unclear`, which asks the patient to repeat - never an
  exception that swallows a reply.

**Before touching this area next:** `agent/llm.py` is not in the section 7
layout. It was added so interpret, respond and knowledge share one pooled
client instead of three copies of the same retry logic.

### 2026-08-23 — Session 5 (WhatsApp: Green API -> Baileys, and live)

**Two provider changes in one day, both driven by the team.** Meta was blocked
on account creation, so Green API went in and was verified authorized. The team
then chose Baileys instead - free, open source, unlimited contacts, and no
third party holding patients' messages, which is a materially better line for a
health pitch than a hosted gateway.

**Cost of the second switch was two files**, exactly as invariant 6 promised.
`client.py` and `parser.py` changed; the ticker, state machine, database and
webhook logic did not.

**Architecture:** Baileys is Node-only and the backend is Python, so
`whatsapp-bridge/` owns the socket and exposes `/send/text`, `/send/buttons`,
`/send/audio` and `/status`, forwarding incoming messages to the backend. It is
deliberately dumb - no business logic, no database.

**Three things found by running it rather than trusting the docs:**

- Baileys' README shows `import makeWASocket, {...}`, which is TypeScript with
  esModuleInterop. In plain ESM the CJS default resolves to the module object,
  giving "makeWASocket is not a function". The **named** export works.
- npm's `latest` tag is **7.0.0-rc14**, a release candidate. Pinned to
  **6.17.16**, the newest stable. Not demoing on an RC.
- The first connection was rejected with **405** because Baileys announced a
  stale WA Web version. It now calls `fetchLatestBaileysVersion()` at connect
  time, which also stops this rotting next month.

**Bugs caught by live testing:**

- **A silent one that mattered:** a leftover `settings.whatsapp_phone_number_id`
  in `webhook.py` threw inside the background task. The webhook still returned
  **200** while every single reply was lost to a log line. That is precisely
  the failure that looks like "WhatsApp is working".
- The outbound path had the same foreign-key flaw already fixed inbound: a
  button payload naming a non-existent dose failed the `message_log` insert, so
  a message we really sent had no audit row. Both paths now verify the dose
  exists before setting the link, and store the payload regardless.

**INVARIANT 2 IS BROKEN, DELIBERATELY, AND NEEDS A REPLACEMENT IN PHASE 3.**

WhatsApp removed interactive buttons for non-official clients. Mainline Baileys
cannot send them; only a community fork or patch can, and those break whenever
WhatsApp changes. The team chose to drop buttons rather than depend on one.

Reply options are therefore sent as numbered text, and the dose id no longer
travels back in a payload. Section 5.2 says never to infer the dose from
timing. The replacement rule Phase 3 must implement:

1. Match the reply to the patient's dose in `AWAITING_REPLY` or
   `REMINDED_AGAIN`, or one `MISSED` within the escalation window.
2. If **exactly one** is open, it is unambiguous - apply it.
3. If **more than one** is open, match on the medicine name in the reply
   ("Panadol le li"), which is why the reminder always names the medicine.
4. Only if that still fails, ask one short question naming the options.

This is not "inferring from timing" - it is resolving against the set of doses
actually awaiting an answer, and refusing to guess when that set is ambiguous.

**Other decisions:**

- **Copy moved into `i18n/strings.py`** and is rendered locally. There are no
  server-side templates on this transport. Strictly better: the wording is
  version-controlled, reviewable in a diff, and changeable in a commit rather
  than an approval queue.
- **Each person is addressed in their own language** now. Under Meta a single
  template-language code applied to everyone; rendering locally means the
  patient gets `patient.language` and the caretaker gets `caretaker.language`.
- **`WEBHOOK_SECRET` is required in the webhook path.** The endpoint is public
  and Baileys has no equivalent of Meta's verify handshake, so without it
  anyone who guessed the URL could post a fake "she took her medicine".
- **`auth_info/` is gitignored in two places.** It is real WhatsApp login
  credentials; anyone holding that folder can read the account's messages.

**Before touching this area next:** the bridge must be running for any send to
work (`make bridge` / `.\bridge.ps1`). `client.bridge_status()` reports the
live connection state and `/api/health` surfaces it.

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
