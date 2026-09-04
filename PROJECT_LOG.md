# MedNuskha — Project Log

> Read `AGENTS.md` first, then this file. Between them a session with no memory
> can pick the project up exactly where it was left.

---

## Current state

**Live, in production, reachable from the internet.** A caretaker signs up at
the Vercel dashboard, adds a family member and their medicines, and the patient
gets WhatsApp reminders at every dose. Replies in Urdu, Roman Urdu or English —
typed or spoken — are understood and drive the dose state. Silence escalates to
the caretaker. Proven on real phones, by people who were not looking for the
happy path.

### Where it runs

| Piece | Where | Notes |
|---|---|---|
| **Dashboard** | Vercel | `mednuskha.vercel.app`, auto-deploys from `main` |
| **Backend** | Hetzner CX23, Falkenstein | `https://api.mednuskha.site`, Caddy + Let's Encrypt |
| **WhatsApp bridge** | same box | Baileys, paired as `923200268481`, session in the `mednuskha_whatsapp-auth` volume |
| **Database** | Supabase **eu-central-1** | Frankfurt, ~9 ms from the server. Was Seoul; see Session 12 |

`ssh mednuskha@2.28.47.28`, code in `~/MedNuskhaV1`, `docker compose ps`.

**A push to `main` deploys itself**: GitHub Actions runs the unit tests, then
SSHes in and runs `scripts/deploy.sh`, which rebuilds only what changed and
fails the deploy if `/api/health` comes back degraded.

### Reading /api/health

`scheduler: running` only means the timer is ticking. **`scheduler_lock: held`
means this is the process that actually sends.** When nothing is arriving, that
is the field to read — and the usual cause is a backend still running on
somebody's laptop against the same Supabase project.

### The safety rules that are load-bearing

Learned the hard way, all of them from a real phone:

- **Consent, not an allowlist.** Nothing but the intro reaches a patient who
  has not replied to it (`whatsapp/client.may_send`). `ALLOWED_NUMBERS` is
  empty and is no longer the guard.
- **A reply is never gated.** Free text to a patient only ever comes from
  `agent.respond`, which runs because they messaged us. `template is None`
  means "we are answering".
- **Ambiguity is about the medicine, not the dose count.**
- **A wrong `taken` is the worst record this system can write** — it falsifies
  the log and switches off the escalation that would have caught it.
- **A voice note that does not say the medicine is worse than no voice note.**

## Current phase

**Shipped and in use.** Every phase Claude can do is done and deployed. The
work now is whatever real use turns up — Session 12 is entirely that, and it
found seven bugs in one evening that no test had.

## Next steps

1. **CR sahab is `stopped=True`** and Affan is `opted_in=False`. Both are
   deliberate states from live testing, not bugs. Resume from the dashboard
   and have Affan reply HAAN if you want them receiving again.
2. **Rotate the credentials that were pasted into a chat transcript**: the
   Supabase database password (`MedNuskha_1234`, weak for an
   internet-facing endpoint), the `sb_secret_` service key, and the GitHub
   Actions `DEPLOY_KEY`. All three still work; none should stay.
3. **Point `mednuskha.site` at Vercel.** The domain is bought and `api.` is
   live; the apex still shows the registrar's parking page. Vercel → Domains,
   then swap the Namecheap parking CNAME and URL-redirect for `A @ 76.76.21.21`
   and `CNAME www cname.vercel-dns.com`.
4. **Phase 7 (prescription OCR)** is the only unbuilt phase and remains the
   stretch.
5. **Doses missed because the server was down** still count against adherence.
   `sent_at IS NULL` means nobody was ever reminded, which is not the patient's
   failure — worth distinguishing in the reports if this matters for the demo.

## Environment / setup

### Running production

```bash
ssh mednuskha@2.28.47.28
cd ~/MedNuskhaV1
docker compose ps                       # both containers, health
docker compose logs -f backend          # the agent, the scheduler, the sends
curl localhost:8000/api/health          # read scheduler_lock, not scheduler
./scripts/deploy.sh                     # what CI runs; --all forces both
python3 scripts/preflight.py            # the settings that fail quietly
```

A push to `main` does all of that on its own. `--all` is the only thing that
restarts the bridge, and restarting the bridge drops the WhatsApp socket.

### Starting it locally

```powershell
.\dev.ps1        # everything: bridge, backend, dashboard
.\bridge.ps1     # the bridge alone, when you need to see the QR code
.\test.ps1       # unit tests
```

`make dev` / `make bridge` / `make test` do the same on Linux, which is what
runs on the ECS box in Phase 8.

> **Do not run the local backend while the server is live.** It takes the
> Postgres advisory lock and the server drops to standby, sending nothing.
> Production recovers on its own within a tick once you stop it, but until
> then no reminders go out. Same for the bridge: one WhatsApp account pairs to
> one bridge, and starting a second knocks the first offline. The unit suite
> is always safe - it touches no services.

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

Remote is **`https://github.com/abzakir/MedNuskhaV1`** (`origin`), branch
`main`. A second remote named `backup` points at `abzakir/MedNuskha`, an older
repository that is **not kept up to date** - deploys clone `origin`.

**A push to `main` deploys.** Tests run first and a failing suite stops it, but
there is no staging: `main` is production. `feat(scope): ...` per §12.
**Claude is not added as a co-author, at the team's request** - no
`Co-Authored-By` trailer, whatever the tooling suggests.

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
- **The running ticker races anything that bulk-inserts doses.**
  `materialise_doses` creates rows for every ACTIVE schedule once a minute, so
  a script that creates a schedule and then inserts its own doses will lose to
  it and die on `uq_dose_event_idempotency_key`. Create the schedule
  `active=False`, insert, then activate - which is what `seed_demo.py` does.
- **Supabase's free-tier pooler drops a connection during anything long.**
  A `make seed` that spends two minutes synthesising voice notes came back to
  `server closed the connection unexpectedly` on the next UPDATE. `db.py`
  already sets `pool_pre_ping=True`, which is what makes the retry work; do not
  remove it, and keep long network work out of an open session.

- **`dev.ps1` runs uvicorn without `--reload`.** A backend started before a
  code change silently 404s on new routes, which looks exactly like a routing
  bug. Restart it, or run a second instance on another port to test against.

- **`ur-PK-UzmaNeural` cannot read Roman Urdu, and fails silently.** Measured
  2026-08-23 by synthesising and transcribing back. Given the reminder copy as
  written for the text message - "Zubaida ji, 8 baj gaye - Panadol 500mg lene
  ka waqt hai" - it **drops the patient's name entirely** and renders "waqt
  hai" as "ہائی". The same sentence in Urdu script round-trips almost word for
  word. This is why `i18n/strings.SPOKEN` exists as a separate dict: the voice
  note is not a reading of the message, it is its own copy.
  - A **Latin medicine name inside an Urdu sentence is fine** - "Panadol
    500mg" comes back as "پینادال پانچ سو ملی گرام". Digits are fine too.
    A **Latin name at the start** is not: it is swallowed. Do not lead a
    spoken line with `{name}`.
  - **Roman Urdu words inside an Urdu sentence lose content.** The stored
    purpose "bukhar aur dard ke liye" speaks as "...aur dard ke liye" -
    *bukhar* (fever) simply gone. Nothing free-text from the database is
    spoken for exactly this reason.
- **`edge_tts` raises `NoAudioReceived` rather than returning empty** when the
  voice has nothing it can say - a bare Latin word, for instance. Uncaught in
  a background task it takes the whole pre-generation run down, so
  `tts.synthesise` converts it to `SynthesisFailed` and callers fall back to
  text.
- **Urdu says the part of day before the hour, and it matters.** Without it
  both 08:00 and 20:00 render "8 baj gaye", which is one cache entry and an
  evening reminder that sounds like a morning one. `strings.period_word`
  prefixes صبح / دوپہر / شام / رات. Caught by the verification script, not by
  reading the code.
- **PyAV needs an explicit resampler for Opus.** Passing decoded MP3 frames
  straight to the encoder fails on layout and rate; `AudioResampler(format=
  "s16", layout="mono", rate=48000)` in between is what produces the mono
  48kHz OGG/Opus invariant 7 requires. Still no ffmpeg binary anywhere.
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

### 2026-09-04 — Session 13 (Documentation visual branding upgrade)

**Integrated official MedNuskha logo assets across project documentation.**

- Added high-resolution horizontal banner (`mednuskha-banner.png`) and mark logo (`mednuskha-logo.jpg`) to `docs/assets/` and `frontend/public/`.
- Upgraded root `README.md`, `frontend/README.md`, and `scripts/verify/README.md` with centered, modern banner images, styled markdown layout, and rich overview descriptions.

### 2026-09-03/04 — Session 12 (deployed, and the bugs a real patient found)

**The product is live.** `https://api.mednuskha.site` on a Hetzner CX23 in
Falkenstein, dashboard on Vercel, database moved to Supabase Frankfurt. Push to
`main` deploys itself. Everything below was found by running it, mostly by a
patient replying to it on a real phone.

**Deployment (see DEPLOY.md, now Hetzner-first):**

- Hetzner **CX23, ~$7/mo** was chosen over Render and Oracle on measurement,
  not taste. The backend peaks at **~800 MB** with the local Whisper model
  loaded and the bridge at ~150 MB, so Render's 512 MB Starter cannot hold it
  without dropping the offline transcriber; a working Render config is ~$32.
  Oracle Always Free runs the same stack for nothing but **reclaims idle
  instances after ~7 days** on free-tier-only accounts, and this workload
  measures 0.5% CPU — upgrade the account to Pay As You Go (bill stays $0) or
  lose the box.
- **The database was 8,500 km from the server.** Supabase was in
  `ap-northeast-2` (Seoul), the server in Germany: **285 ms per query, 1,137 ms
  per fresh connection**, and a page load makes dozens. That, not the code, was
  why adding a patient took 1–2 minutes. Moved to `eu-central-1`: **9 ms and
  34 ms — 32× faster.** If the app ever feels slow again, measure the round
  trip before touching a query.
- `scripts/preflight.py` (stdlib only, runs on a bare box) checks the settings
  that fail *quietly*: a report link still pointing at localhost, an empty
  allowlist, `DEV_AUTH_BYPASS` left on.
- `scripts/deploy.sh` + `.github/workflows/deploy.yml`: tests must pass, then
  SSH, then rebuild **only what changed**. A backend-only commit does not
  restart the bridge — restarting it drops the WhatsApp socket and every
  message a patient sends during the reconnect is gone, because Baileys is not
  a queue.
- The health gate was written inline in the shell **twice and broke twice**,
  both times on quoting. Both failures looked identical and were the bad kind:
  the gate crashes, the retry loop burns every attempt, and a *healthy* deploy
  reports FAILED. It is `scripts/healthgate.py` now — a file has no quoting
  layer to get wrong.

**Bugs a real patient found, in the order they hurt:**

1. **The reminder announced the wrong hour.** `dose_event` timestamps come back
   from Postgres **naive**, and `.astimezone()` on a naive datetime assumes the
   *machine's* timezone rather than UTC. On a PKT laptop that read 04:30 UTC as
   04:30 PKT and told a patient "4 baj gaye" for a 09:30 dose. **Invisible on a
   UTC server**, which is why it survived — there the wrong assumption happens
   to be right. Minutes are spoken now too.
2. **"HAAN" to the intro was recorded as a dose taken.** The opt-in gate
   existed and was correct, but nothing opened it: `create_patient` set
   `opted_in=True`, so the gate never fired and the HAAN went down the ordinary
   reply path, where it is an unambiguous confirmation. Sending the intro now
   sets `opted_in=False` — asking for consent waits for it — and
   `create_patient` no longer defaults it true, which is what §4.4 said all
   along.
3. **"Yes, I have taken this" was answered "Sorry, I didn't catch that", three
   times.** Whisper transcribed it perfectly and the model classified it
   correctly. `resolve_dose` counted **doses** where it should have counted
   **medicines**: three doses across two medicines, so everything downstream
   read "I don't know which" as "I don't know what". Two open doses of one
   medicine are no longer a question — which alone makes a twice-daily
   prescription answerable again.
4. **"I bought a Panadol." → "panadol taken - it's noted."** Buying is not
   taking. The fast path correctly stayed out; the model read acquisition as
   consumption. A wrong `taken` is the worst record here — it falsifies the log
   **and** switches off the escalation that would have caught it, so the
   mistake hides itself.
5. **The voice note never said the medicine.** `ur-PK-UzmaNeural` silently
   drops Latin words it cannot transliterate. Measured: "Panadol 500mg",
   "Inderal 10mg" and "Amlodipine 5mg" are said correctly; **"polymalt" is
   dropped entirely** and "polymalt syrup" keeps only "syrup". Checked now by
   *difference* — synthesise with and without the name, and if the transcripts
   match it contributed nothing — which needs no transliteration of a drug
   name, the one thing this product will not guess at.
6. **Voice notes died from day two of every course.** `voice_note_key` is
   written once at pre-generation, which can only reach doses that exist then,
   while materialisation runs 24 h ahead. A null key now resolves through the
   content hash. A separate top-up job every 10 min repairs a pre-generation
   that never finished.
7. **A forwarded voice note was recorded as a dose taken**, and the escalation
   that would have caught it switched off. The bridge reads WhatsApp's
   forwarded flag now; nothing that changes the record may come from one.

**Two bugs I introduced and then found the same night:**

- The consent gate refused **the message confirming a STOP had worked**, and
  every reply after it. The patient asked "Why are you not answering me?" into
  silence. STOP silences what we *start*; it does not make us ignore somebody
  who just wrote to us.
- The same gate refused a **`caretaker_alert`** because that caretaker's number
  also belonged to an un-opted-in patient. Escalation — the entire product —
  was off.

**The rule that came out of both:** free text to a patient only ever comes from
`agent.respond`, which runs *because they messaged us*. Reminders are always
templates. So `template is None` **is** "we are answering", and it is never
gated.

**ALLOWED_NUMBERS is no longer the guard.** It was bad in both directions: it
silently blocked three real patients until someone edited `.env` and restarted
the bridge, and it would not have caught a typo anyway, because a wrong digit
is a perfectly valid `patient` row somebody would dutifully add to the list.
Consent catches what the list could not — *"is this number registered"* allows
a typo, *"has a human on this handset replied"* does not.

**Before touching this area next:**

- **Never run the local backend while the server is live.** It takes the
  Postgres advisory lock and the server drops to standby, sending nothing. I
  did this and production went quiet for two minutes. The failover recovers on
  its own within a tick, but the lock is the thing to check first when
  reminders stop: `/api/health` → `scheduler_lock`, not `scheduler`.
- `scheduler` says the timer is ticking. **`scheduler_lock: held` says this is
  the process that actually sends.** Those are different, and only the second
  one matters when nothing is arriving.
- The unit suite must stay offline. It reached live Supabase for a while and a
  "pure" test took 4.6 s and failed on network wobble; it is 1.7 s now.

### 2026-08-26 — Session 11 (the caretaker conversation deadlock)

**Found on a real phone, by a real caretaker.** usman sent `status`, the agent
asked "Kis ke baare mein? Affan Jani, Zubaida Bibi [demo]", he answered
"Affan jaani" — and got "samajh nahi aaya". Then "Affan". Same. The agent asked
a question it could not accept the answer to, and the conversation deadlocked
permanently.

**Two independent faults, either of which alone would have caused it:**

1. **`_pick` matched only the WHOLE stored name as a substring.** "Affan Jani"
   is the row; `"affan jani" in "affan jaani"` is False, and so is
   `"affan jani" in "affan"`. So a first name alone failed, and one extra
   letter failed. Nobody types a name the way a database stores it.
2. **Nothing remembered that a question had been asked.** Every message was
   interpreted standalone. A bare name matches no command regex, the model
   classified it `other`, and it fell through to the unclear branch — which is
   correct behaviour for a message with no context, and useless here.

**The fix:**

- `_pick` now runs three passes, loosest last: full name, then any identifying
  word ("Affan"), then a fuzzy match for spelling drift ("jaani" → "Jani", at a
  0.82 ratio, which accepts that and rejects "Adnan"). Honorifics and the
  `[demo]` tag are stripped as non-identifying.
- **Ambiguity still returns None, deliberately.** If two patients match, it
  asks again. Asking costs one message; guessing could pause the wrong
  person's reminders.
- A short-lived `_AWAITING` map remembers which command is waiting on a name,
  for 10 minutes. When the next message names a patient and matches no command,
  it completes the pending one.
- A name arriving with **nothing** pending now gets "what about Affan Jani?"
  plus the three commands, rather than a shrug. We knew who, just not what.
- A name we recognise but cannot pin down gets a distinct reply asking for the
  full name — different from "I did not understand you".

**Key decisions:**

- **The pending question lives in memory, not the database.** §8 froze the
  schema and this is worth ten minutes of state, not a migration. One process
  holds the scheduler advisory lock so there is exactly one of these. A restart
  loses a half-finished question, which costs the caretaker one extra word.
- **10-minute TTL.** Long enough to walk to the kitchen and answer; short
  enough that tomorrow's "Affan" is not read as an answer to today's question.
  Pinned by a test that expires the entry and checks it is dropped.
- **Clinical and help clear the pending question.** Otherwise a refusal
  followed by a name would silently run the command that was pending before it.

**Two test-suite repairs, neither a product bug:**

- `verify_caretaker.py` assumed the caretaker had exactly ONE patient, so bare
  `status` returned a report. `make seed` attached the demo patient to the most
  recent caretaker, giving usman two — so `status` correctly asked which one
  and four checks failed. The suite now names a patient when there is more than
  one, and is agnostic to how many there are.
- `verify_agent.py` deleted the shared `panadol` reference row on cleanup.
  Reference rows are **one per medicine name across the whole system**, so once
  `make seed` created a real Panadol the delete hit a ForeignKeyViolation. It
  now only deletes a row nothing else references, and otherwise just clears its
  `confirmed_by` link.

**Before touching this area next:** `_pick` returning None is a feature. Every
loosening of it must keep the "two matches means ask, never guess" rule — the
blast radius of picking the wrong patient is somebody's medication.

### 2026-08-24 — Session 10 (Phase 8: the parts that are not the deploy)

**Done:** `Dockerfile` for the backend, `whatsapp-bridge/Dockerfile`,
`docker-compose.yml`, a real `README.md` with an architecture diagram, and
`scripts/seed_demo.py`. §14 is explicit that the provisioning and deploying are
the team's, not Claude's, so this is everything up to the point where someone
has to log into Alibaba Cloud.

**A race the seed script found:** inserting dose rows for a freshly created
schedule collides with the running ticker, which materialises doses for every
**active** schedule once a minute. The second `make seed` died on
`uq_dose_event_idempotency_key` for a dose the ticker had created in the gap.
Schedules are now created `active=False` and switched on once every row is in
place - `materialise_doses` filters on `Schedule.active`, so an inactive
schedule is invisible to it. Worth knowing for anything else that bulk-inserts
doses.

**Key decisions:**

- **The seed attaches to the caretaker who signed in most recently**, rather
  than creating its own. The dashboard only ever shows one family's data, so a
  demo under a caretaker nobody signs in as is a demo nobody can see.
  `--email` overrides it.
- **The default patient number is in a reserved test range**, and `--phone`
  is what makes a demo live. A seed script that starts messaging a real phone
  the moment someone runs it is a bad default.
- **Three medicines with three different stories** - one steady, one perfect,
  one where the evening dose is the problem. A demo needs a shape the presenter
  can talk over, and it exercises every branch of both reports: the caretaker
  PDF's "hardest time of day" only says something interesting if one exists.
- **Seeded symptoms are deliberately not linked to a dose.** The system does
  not know which medicine a symptom relates to and invariant 8 forbids it
  guessing. Unlinked is the truthful record, and it also means the urgent one
  shows on whichever report gets opened rather than on whichever medicine
  happened to share the 08:00 slot.
- **Doses in the future are left SCHEDULED**, not backdated. Backdating a dose
  that has not happened is the one thing that would make the dashboard lie.
- **One uvicorn worker in the container.** A Postgres advisory lock already
  stops a second process running the ticker, so extra workers would serve
  requests but sit idle on the schedule - and the lock warning reads like a bug
  to whoever finds it next.
- **`make bridge` existed in `.PHONY` but had no rule**, while this log and the
  README both told people to run it. Added.
- **`ALLOWED_NUMBERS` was undocumented**, and empty means *no restriction* -
  the bridge will message anyone it is asked to. Now in `.env.example` with
  that stated plainly, and in the README's pre-deploy list.

**Not done:** neither image has been built - Docker is not installed here. The
code has no 3.12+ syntax or stdlib, so `python:3.11-slim` should be right, but
that first build is unproven.

**Before touching this area next:** the Dockerfiles have no `apt install` line
and that is load-bearing, not an oversight. Dropping WeasyPrint removed GTK and
Pango; PyAV bundles FFmpeg in its wheel. If a system package looks necessary,
check whether a dependency changed first.

### 2026-08-24 — Session 9 (Phase 5: the voice notes)

**Done:** `voice/tts.py` and `voice/store.py`, spoken copy in
`i18n/strings.SPOKEN`, pre-generation wired to the two medicine endpoints, and
the voice note attached in `ticker.send_reminder` / `send_followup`. 32/32
against live edge-tts and the live database, 25 new unit tests (107 total).

**The finding that shaped everything: this voice cannot read Roman Urdu.**
Measured before writing any of it, by synthesising and transcribing back with
the whisper model the project already trusts. The reminder copy as written for
the text message loses the patient's name and mangles "waqt hai". The same
sentence in Urdu script comes back almost word for word. So the voice note is
**not a reading of the message** - `SPOKEN` is its own dict, in Urdu script,
and the two are allowed to differ.

**Key decisions:**

- **Nothing from the database is ever spoken.** The confirmed purpose is
  stored in Roman Urdu, and spoken aloud "bukhar aur dard ke liye" comes out
  as "...aur dard ke liye" - the word *fever* silently gone. That makes the
  third bullet of Phase 5's "Done when" undeliverable on the current data, and
  the right answer was to not ship it rather than ship audio that drops
  clinical words. Only templates written in Urdu script are spoken. A purpose
  typed in Urdu script would work today; it is a data fix, not a code one.
- **Cache keys are content-addressed** - a hash of the voice plus the exact
  sentence. §14 asks for caching by `(medicine, dose_time)`; hashing the
  sentence *is* that, and it also means two patients on the same medicine at
  the same hour share a file, and that changing the copy can never serve the
  old audio. Verified: 28 doses, 2 files.
- **Local disk is the primary store, not a cache in front of Supabase.** The
  opposite of the reports, and deliberately: the ticker reads this at the
  moment a dose is due, and §3.4 forbids synthesising there. It also means the
  feature works with `SUPABASE_SERVICE_KEY` unset, which it currently is.
- **The "never synthesise in the reminder path" rule is tested, not asserted.**
  `verify_voice.py` replaces `tts.synthesise` with a function that raises, then
  sends a reminder and checks the voice note still went. That is the only
  honest way to prove a negative about a code path.
- **Urdu needs the part of day before the hour.** Without it 08:00 and 20:00
  are the same sentence, one cache file, and an evening reminder that says
  "morning". Found by the verification script asserting the two should differ -
  the test was written expecting a pass and failed, which is the good kind.
- **Voice replies match the modality.** A patient who sends a voice note gets
  one back; a patient who types gets text. Someone sending voice is often
  someone who finds reading hard, and a surprise audio clip for someone who
  typed is noise.
- **`app/storage.py` was extracted** so reports and voice share one Supabase
  Storage client instead of two copies of the RLS handling. Not in the §7
  layout; §7 updated.
- **Text copy was left alone.** The text reminder still says "8 baj gaye" for
  both times. Changing it would mean re-verifying Phase 2's 42 checks for a
  cosmetic gain, and the patient can see the clock. Worth doing if that copy
  is ever touched for another reason.

**Not done:** nobody has heard these files. The round trip proves the words are
right, not that the voice sounds right - §14 asks a human to judge that, and it
is step 1 of Next steps along with the report buttons.

**Before touching this area next:** `strings.SPOKEN` is the whitelist. If a
message has no entry there it is never spoken, and that is the mechanism
keeping database free text out of the audio - not a check somewhere in the
send path that could be forgotten.

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
