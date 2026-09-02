/**
 * MedNuskha WhatsApp bridge.
 *
 * Baileys is Node-only and the rest of MedNuskha is Python, so this process
 * owns the WhatsApp socket and exposes a small HTTP surface the FastAPI
 * backend talks to. It is deliberately dumb: it sends what it is told and
 * forwards what arrives. No business logic, no database, no state machine.
 *
 * Outbound (called by backend/app/whatsapp/client.py):
 *   GET  /status         connection state, and the QR string while pairing
 *   POST /send/text      { to, body }
 *   POST /send/buttons   { to, body, buttons: [{id, text}] }
 *   POST /send/audio     { to, audioBase64, ptt }
 *
 * Inbound: every incoming message is POSTed to
 *   {BACKEND_WEBHOOK_URL}   as { id, from, type, text, buttonId, audioBase64 }
 *
 * The auth_info/ folder holds real WhatsApp login credentials. It is
 * gitignored. Anyone with that folder can read the account's messages.
 */

import { Boom } from '@hapi/boom'
// Baileys' README shows `import makeWASocket, {...}` - that is TypeScript with
// esModuleInterop. In plain ESM the CJS default resolves to the module object,
// not the function, and you get "makeWASocket is not a function". The named
// export is the one that works here.
import {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  getContentType,
  isLidUser,
  makeWASocket,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys'
import express from 'express'
import pino from 'pino'
import qrcode from 'qrcode-terminal'

const PORT = Number(process.env.BRIDGE_PORT || 3001)
// Loopback by default. This process will send a WhatsApp message to anyone who
// can reach it and has no authentication of its own, so on a bare-metal host
// binding every interface hands the account to the internet. Docker overrides
// this to 0.0.0.0 because there the backend reaches it by service name and the
// published port is already pinned to 127.0.0.1 (see docker-compose.yml).
const HOST = process.env.BRIDGE_HOST || '127.0.0.1'
const BACKEND_WEBHOOK_URL =
  process.env.BACKEND_WEBHOOK_URL || 'http://127.0.0.1:8000/webhook'
const AUTH_DIR = process.env.AUTH_DIR || './auth_info'
// Green API had a 3-chat cap; Baileys has none. This exists only so a
// mis-typed number during testing cannot message a stranger.
const ALLOWLIST = (process.env.ALLOWED_NUMBERS || '')
  .split(',')
  .map((n) => n.replace(/\D/g, ''))
  .filter(Boolean)

const log = pino({
  level: process.env.LOG_LEVEL || 'info',
  transport: { target: 'pino-pretty', options: { translateTime: 'HH:MM:ss', ignore: 'pid,hostname' } },
})

let sock = null
let connectionState = 'disconnected'
let currentQR = null
let meNumber = null

/** Digits only, no + and no leading zero: 923001234567. */
function normalise(raw) {
  let d = String(raw || '').replace(/\D/g, '')
  if (d.startsWith('00')) d = d.slice(2)
  if (d.startsWith('0')) d = '92' + d.replace(/^0+/, '')
  return d
}

const toJid = (number) => `${normalise(number)}@s.whatsapp.net`
const fromJid = (jid) => normalise(String(jid || '').split('@')[0].split(':')[0])

/**
 * Work out the real phone number behind a message.
 *
 * WhatsApp increasingly addresses senders by LID - a privacy identifier like
 * 109784363725047@lid - instead of their phone number. Observed live on
 * 2026-08-23: a patient's reply arrived from a LID and could not be matched to
 * anyone, which in a medication app means a confirmed dose silently going
 * unrecorded.
 *
 * Three sources, best first:
 *   1. key.remoteJidAlt / participantAlt - the phone number the server sent
 *      alongside the LID.
 *   2. the signal store's LID -> PN mapping, learned from earlier traffic.
 *   3. the LID itself, so the message is still delivered and logged rather
 *      than dropped. The backend will not match it, and says so loudly.
 */
async function resolveSender(m) {
  const jid = m.key.remoteJid || ''
  if (!isLidUser(jid)) return { from: fromJid(jid), lid: null }

  const alt = m.key.remoteJidAlt || m.key.participantAlt
  if (alt) return { from: fromJid(alt), lid: fromJid(jid) }

  try {
    const pn = await sock?.signalRepository?.lidMapping?.getPNForLID?.(jid)
    if (pn) return { from: fromJid(pn), lid: fromJid(jid) }
  } catch (err) {
    log.warn(`LID lookup failed for ${jid}: ${err.message}`)
  }

  log.warn(`could not resolve ${jid} to a phone number - forwarding the LID`)
  return { from: fromJid(jid), lid: fromJid(jid), unresolved: true }
}

function allowed(number) {
  return ALLOWLIST.length === 0 || ALLOWLIST.includes(normalise(number))
}

// ---------------------------------------------------------------- socket

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)

  // WhatsApp rejects the handshake with a 405 if the client announces a stale
  // WA Web version. Ask Baileys what the current one is rather than shipping a
  // number that goes out of date the week after the hackathon.
  const { version, isLatest } = await fetchLatestBaileysVersion()
  log.info(`WA Web version ${version.join('.')}${isLatest ? '' : ' (not latest)'}`)

  sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'silent' }),
    // We render the QR ourselves so it can also be served over /status.
    printQRInTerminal: false,
    // A recognised browser signature. A custom string is another way to get
    // a 405.
    browser: Browsers.macOS('Desktop'),
    markOnlineOnConnect: false,
    syncFullHistory: false,
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update

    if (qr) {
      currentQR = qr
      connectionState = 'qr'
      log.info('scan this QR with the SPARE phone (WhatsApp > Linked devices):')
      qrcode.generate(qr, { small: true })
    }

    if (connection === 'open') {
      connectionState = 'connected'
      currentQR = null
      meNumber = fromJid(sock.user?.id)
      log.info(`connected as ${meNumber}`)
      if (ALLOWLIST.length) log.info(`allowlist active: ${ALLOWLIST.join(', ')}`)
    }

    if (connection === 'close') {
      const status = new Boom(lastDisconnect?.error)?.output?.statusCode
      const loggedOut = status === DisconnectReason.loggedOut
      connectionState = loggedOut ? 'logged_out' : 'disconnected'
      log.warn(`connection closed (${status}) - ${loggedOut ? 'LOGGED OUT' : 'reconnecting'}`)

      if (loggedOut) {
        log.error(
          `this device was unlinked. Delete ${AUTH_DIR}/ and restart to pair again.`
        )
        return
      }
      setTimeout(connect, 3000)
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const m of messages) {
      try {
        await handleIncoming(m)
      } catch (err) {
        log.error(`failed handling ${m?.key?.id}: ${err.message}`)
      }
    }
  })
}

// -------------------------------------------------------------- inbound

/**
 * Message types WhatsApp sends for its own bookkeeping, not because a human
 * typed anything. Forwarding these made the activity log show the patient
 * saying "other" every few minutes, and would have the agent trying to
 * interpret a read receipt.
 */
const IGNORED_TYPES = new Set([
  'protocolMessage',        // revokes, ephemeral settings, history sync
  'senderKeyDistributionMessage',
  'messageContextInfo',
  'reactionMessage',        // an emoji reaction is not an answer
  'pollUpdateMessage',
  'keepInChatMessage',
  'stickerSyncRmrMessage',
])

async function handleIncoming(m) {
  if (!m.message) return
  if (m.key.fromMe) return                       // our own outgoing message
  const jid = m.key.remoteJid || ''
  if (jid.endsWith('@g.us') || jid === 'status@broadcast') return  // groups/status

  const { from, lid, unresolved } = await resolveSender(m)
  const contentType = getContentType(m.message)

  if (!contentType || IGNORED_TYPES.has(contentType)) {
    log.debug(`skipping ${contentType} from ${from} - not a human message`)
    return
  }

  // Whether WhatsApp says this was forwarded rather than composed now.
  // A forwarded voice note is the patient passing something along, not
  // answering us, and the backend must not read it as a dose reply.
  const content = m.message[contentType]
  const ctx = content && typeof content === 'object' ? content.contextInfo : null
  const forwarded = Boolean(ctx && (ctx.isForwarded || (ctx.forwardingScore || 0) > 0))

  const payload = {
    id: m.key.id,
    from,
    timestamp: Number(m.messageTimestamp) || Math.floor(Date.now() / 1000),
    type: 'other',
    text: null,
    buttonId: null,
    audioBase64: null,
    forwarded,
    raw: { contentType, lid: lid || undefined, unresolved: unresolved || undefined },
  }

  switch (contentType) {
    case 'conversation':
      payload.type = 'text'
      payload.text = m.message.conversation
      break

    case 'extendedTextMessage':
      payload.type = 'text'
      payload.text = m.message.extendedTextMessage?.text
      break

    case 'buttonsResponseMessage':
      payload.type = 'button'
      payload.buttonId = m.message.buttonsResponseMessage?.selectedButtonId
      payload.text = m.message.buttonsResponseMessage?.selectedDisplayText
      break

    case 'templateButtonReplyMessage':
      payload.type = 'button'
      payload.buttonId = m.message.templateButtonReplyMessage?.selectedId
      payload.text = m.message.templateButtonReplyMessage?.selectedDisplayText
      break

    case 'listResponseMessage':
      payload.type = 'button'
      payload.buttonId =
        m.message.listResponseMessage?.singleSelectReply?.selectedRowId
      payload.text = m.message.listResponseMessage?.title
      break

    case 'interactiveResponseMessage': {
      payload.type = 'button'
      const body = m.message.interactiveResponseMessage?.nativeFlowResponseMessage
      try {
        const parsed = JSON.parse(body?.paramsJson || '{}')
        payload.buttonId = parsed.id || parsed.selectedId || null
      } catch {
        payload.buttonId = null
      }
      break
    }

    case 'audioMessage': {
      payload.type = 'audio'
      const buffer = await downloadMediaMessage(
        m,
        'buffer',
        {},
        { reuploadRequest: sock.updateMediaMessage }
      )
      payload.audioBase64 = buffer.toString('base64')
      payload.raw.ptt = !!m.message.audioMessage?.ptt
      payload.raw.seconds = m.message.audioMessage?.seconds
      break
    }

    case 'imageMessage': {
      payload.type = 'image'
      payload.text = m.message.imageMessage?.caption || null
      const buffer = await downloadMediaMessage(
        m,
        'buffer',
        {},
        { reuploadRequest: sock.updateMediaMessage }
      )
      payload.imageBase64 = buffer.toString('base64')
      break
    }

    default:
      payload.type = 'other'
  }

  log.info(
    `in  ${from}${lid ? ` (lid ${lid})` : ''} ${payload.type}` +
      (forwarded ? ' [forwarded]' : '') +
      (payload.buttonId ? ` [${payload.buttonId}]` : '') +
      (payload.text ? ` ${JSON.stringify(payload.text).slice(0, 60)}` : '')
  )

  await forward(payload)
}

/** POST to the Python backend, retrying briefly if it is still starting. */
async function forward(payload, attempt = 1) {
  try {
    const res = await fetch(BACKEND_WEBHOOK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error(`backend returned ${res.status}`)
  } catch (err) {
    if (attempt <= 3) {
      log.warn(`forward failed (${err.message}) - retry ${attempt}/3`)
      setTimeout(() => forward(payload, attempt + 1), 1000 * attempt)
    } else {
      log.error(`GAVE UP forwarding ${payload.id}: ${err.message}`)
    }
  }
}

// ------------------------------------------------------------- outbound

function requireReady(res) {
  if (connectionState !== 'connected' || !sock) {
    res.status(503).json({
      error: 'whatsapp not connected',
      state: connectionState,
      hint: connectionState === 'qr'
        ? 'scan the QR code printed in this terminal'
        : 'check the bridge logs',
    })
    return false
  }
  return true
}

const app = express()
app.use(express.json({ limit: '25mb' }))

// Diagnostic: what does WhatsApp say about a number, and does it hand back a
// LID we can map replies to?
app.get('/resolve/:number', async (req, res) => {
  if (!requireReady(res)) return
  try {
    const result = await sock.onWhatsApp(normalise(req.params.number))
    res.json({ query: normalise(req.params.number), result })
  } catch (err) {
    res.status(502).json({ error: err.message })
  }
})

app.get('/status', (_req, res) => {
  res.json({
    state: connectionState,
    qr: currentQR,
    me: meNumber,
    allowlist: ALLOWLIST,
  })
})

app.post('/send/text', async (req, res) => {
  if (!requireReady(res)) return
  const { to, body } = req.body || {}
  if (!to || !body) return res.status(400).json({ error: 'to and body required' })
  if (!allowed(to)) return res.status(403).json({ error: `${to} not in ALLOWED_NUMBERS` })

  try {
    const sent = await sock.sendMessage(toJid(to), { text: String(body) })
    log.info(`out ${normalise(to)} text`)
    res.json({ id: sent.key.id })
  } catch (err) {
    log.error(`send text to ${to} failed: ${err.message}`)
    res.status(502).json({ error: err.message })
  }
})

/**
 * Interactive buttons.
 *
 * WhatsApp removed button support for non-official clients, so mainline
 * Baileys cannot render them. Rather than depend on a community fork that
 * breaks whenever WhatsApp changes something, this degrades to a numbered
 * text message and reports which mode it used, so the backend knows whether
 * a tap is coming or a typed reply.
 */
app.post('/send/buttons', async (req, res) => {
  if (!requireReady(res)) return
  const { to, body, buttons } = req.body || {}
  if (!to || !body) return res.status(400).json({ error: 'to and body required' })
  if (!allowed(to)) return res.status(403).json({ error: `${to} not in ALLOWED_NUMBERS` })

  const options = Array.isArray(buttons) ? buttons : []

  try {
    const lines = options.map((b, i) => `${i + 1}. ${b.text}`).join('\n')
    const text = options.length ? `${body}\n\n${lines}` : String(body)
    const sent = await sock.sendMessage(toJid(to), { text })
    log.info(`out ${normalise(to)} buttons-as-text (${options.length} options)`)
    res.json({ id: sent.key.id, mode: 'text' })
  } catch (err) {
    log.error(`send buttons to ${to} failed: ${err.message}`)
    res.status(502).json({ error: err.message })
  }
})

app.post('/send/audio', async (req, res) => {
  if (!requireReady(res)) return
  const { to, audioBase64, ptt = true } = req.body || {}
  if (!to || !audioBase64) {
    return res.status(400).json({ error: 'to and audioBase64 required' })
  }
  if (!allowed(to)) return res.status(403).json({ error: `${to} not in ALLOWED_NUMBERS` })

  try {
    const sent = await sock.sendMessage(toJid(to), {
      audio: Buffer.from(audioBase64, 'base64'),
      // ptt:true is what makes WhatsApp render a play button instead of a
      // file attachment an elderly user will never tap (invariant 7).
      mimetype: 'audio/ogg; codecs=opus',
      ptt: Boolean(ptt),
    })
    log.info(`out ${normalise(to)} voice note`)
    res.json({ id: sent.key.id })
  } catch (err) {
    log.error(`send audio to ${to} failed: ${err.message}`)
    res.status(502).json({ error: err.message })
  }
})

app.listen(PORT, HOST, () => {
  log.info(`bridge listening on http://${HOST}:${PORT}`)
  log.info(`forwarding incoming messages to ${BACKEND_WEBHOOK_URL}`)
  connect().catch((err) => log.error(`connect failed: ${err.message}`))
})
