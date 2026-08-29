/**
 * The single place the dashboard talks to the FastAPI backend.
 *
 * Every request carries the Supabase access token, so the backend can map it
 * to a caretaker and enforce that they only ever see their own family.
 */

import { getSession } from "./supabase";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Fetch a PDF with the caretaker's token attached and open it in a new tab.
 *
 * A plain <a href> cannot carry the Bearer header, so the file is fetched,
 * turned into a blob URL and opened from there. The object URL is revoked on
 * a timer rather than immediately - revoking it straight away races the new
 * tab and shows a blank viewer. */
export async function openPdf(path: string, filename: string): Promise<void> {
  const session = await getSession();
  const headers: Record<string, string> = {};
  if (session?.access_token) {
    headers.Authorization = `Bearer ${session.access_token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { headers, cache: "no-store" });
  } catch {
    throw new ApiError(
      `Can't reach the server at ${API_BASE}. Is the backend running?`,
      0,
    );
  }
  if (!res.ok) {
    let message = `Could not build the report (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* keep the default */
    }
    throw new ApiError(message, res.status);
  }

  const url = URL.createObjectURL(await res.blob());
  const opened = window.open(url, "_blank");
  if (!opened) {
    // Pop-up blocked - fall back to a download so the click is not wasted.
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const session = await getSession();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (session?.access_token) {
    headers.Authorization = `Bearer ${session.access_token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError(
      `Can't reach the server at ${API_BASE}. Is the backend running?`,
      0,
    );
  }

  if (!res.ok) {
    // FastAPI puts the useful part in `detail`; validation errors nest it.
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg)
        message = body.detail[0].msg.replace(/^Value error, /, "");
    } catch {
      /* keep the default */
    }
    throw new ApiError(message, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

// ---------------------------------------------------------------- types

export type DoseState =
  | "SCHEDULED"
  | "SENT"
  | "AWAITING_REPLY"
  | "REMINDED_AGAIN"
  | "TAKEN"
  | "TAKEN_LATE"
  | "MISSED"
  | "SKIPPED";

export type Adherence = {
  taken: number;
  on_time: number;
  late: number;
  missed: number;
  skipped: number;
  pending: number;
  decided: number;
  percent: number | null;
  days: number;
};

export type Me = {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  relation: string;
  language: string;
  family: { id: string | null; name: string | null };
  patient_count: number;
  needs_phone: boolean;
};

export type PatientSummary = {
  id: string;
  name: string;
  whatsapp_number: string;
  language: string;
  opted_in: boolean;
  stopped: boolean;
  medicine_count: number;
  today: { total: number; taken: number; missed: number; pending: number };
  adherence: Adherence;
};

export type MedicineDetail = {
  id: string;
  name: string;
  strength: string | null;
  form: string | null;
  active: boolean;
  schedule: {
    dose_times: string[];
    duration_days: number | null;
    start_date: string | null;
    end_date: string | null;
    days_remaining: number | null;
    finished: boolean;
  } | null;
  info: {
    purpose_ur: string | null;
    purpose_en: string | null;
    food_rule: string | null;
    confirmed: boolean;
  } | null;
  adherence: Adherence;
};

export type PatientDetail = {
  id: string;
  name: string;
  whatsapp_number: string;
  language: string;
  opted_in: boolean;
  stopped: boolean;
  medicines: MedicineDetail[];
  adherence: Adherence;
};

export type Dose = {
  id: string;
  medicine_id: string;
  medicine: string;
  state: DoseState;
  scheduled_at: string;
  time: string;
  sent_at: string | null;
  responded_at: string | null;
  response_source: string | null;
  response_text: string | null;
  reason: string | null;
  caretaker_alerted: boolean;
};

export type Today = {
  patient_id: string;
  date: string;
  server_time: string;
  doses: Dose[];
  summary: { total: number; taken: number; missed: number; pending: number };
};

export type PatientContact = {
  id: string;
  name: string;
  whatsapp_number: string;
  language: string;
  opted_in: boolean;
  stopped: boolean;
  /** True when the number changed: the new handset must opt in before we send. */
  needs_optin: boolean;
};

export type History = {
  patient_id: string;
  days: number;
  doses: Dose[];
};

export type EventRow = {
  kind: "message" | "symptom";
  at: string;
  direction?: "in" | "out";
  type?: string;
  body: string | null;
  template?: string | null;
  status?: string | null;
  error?: string | null;
  severity?: string;
};

export type MedicineDraft = {
  source: "existing" | "ai_fetched";
  already_confirmed: boolean;
  recognised?: boolean;
  canonical_name: string;
  purpose_ur: string | null;
  purpose_en: string | null;
  food_rule: string | null;
  common_timing: string | null;
  aliases: string[];
  confirmed: boolean;
};

export type WhatsAppStatus = {
  state: string;
  me?: string | null;
  qr?: string | null;
  error?: string;
};

// ------------------------------------------------------------- endpoints

export const api = {
  me: () => get<Me>("/api/me"),
  updateMe: (body: Partial<Pick<Me, "name" | "phone" | "relation" | "language">>) =>
    patch<Me>("/api/me", body),

  patients: () => get<PatientSummary[]>("/api/patients"),
  patient: (id: string) => get<PatientDetail>(`/api/patients/${id}`),
  today: (id: string) => get<Today>(`/api/patients/${id}/today`),
  events: (id: string) => get<EventRow[]>(`/api/patients/${id}/events`),

  /** Every dose over the last N days, for the adherence chart. */
  history: (id: string, days = 14) =>
    get<History>(`/api/patients/${id}/history?days=${days}`),

  /**
   * Delete a patient and their whole history. Irreversible, and it releases
   * their WhatsApp number so the same person can be added again later.
   * `confirm` must be the patient's exact name.
   */
  deletePatient: (id: string, confirm: string) =>
    del<{ deleted: boolean; name: string; number_released: string }>(
      `/api/patients/${id}?confirm=${encodeURIComponent(confirm)}`,
    ),

  /**
   * Delete this caretaker's own account. Takes their patients with it when
   * nobody else is left in the family, and releases every number involved.
   */
  deleteMe: (confirm: string) =>
    del<{
      deleted: boolean;
      name: string;
      patients_removed: string[];
      numbers_released: string[];
      family_removed: boolean;
      auth_deleted: boolean;
    }>(`/api/me?confirm=${encodeURIComponent(confirm)}`),

  /** Correct a patient's name, WhatsApp number or language. */
  updatePatient: (
    id: string,
    body: { name?: string; whatsapp_number?: string; language?: string },
  ) => patch<PatientContact>(`/api/patients/${id}`, body),

  addPatient: (body: {
    name: string;
    whatsapp_number: string;
    language: string;
    relation: string;
  }) => post<{ id: string }>("/api/patients", body),

  sendOptin: (id: string) => post<{ sent: boolean }>(`/api/patients/${id}/optin`),

  /** Build and open one of the two reports for a medicine's course. */
  openReport: (
    patientId: string,
    kind: "doctor" | "caretaker",
    medicineId?: string,
  ) =>
    openPdf(
      `/api/patients/${patientId}/report.pdf?kind=${kind}` +
        (medicineId ? `&medicine_id=${medicineId}` : ""),
      `mednuskha-${kind}.pdf`,
    ),

  /** Undo a STOP - a phrase can be misread, and without this every
   *  future reminder stays silently dead. */
  resumePatient: (id: string) =>
    post<{ resumed: boolean; doses_created: number }>(
      `/api/patients/${id}/resume`,
    ),

  lookupMedicine: (name: string) =>
    post<MedicineDraft>("/api/medicines/lookup", { name }),

  addMedicine: (body: {
    patient_id: string;
    name: string;
    strength?: string;
    form?: string;
    dose_times: string[];
    duration_days: number;
    purpose_ur?: string;
    purpose_en?: string;
    food_rule?: string;
    common_timing?: string;
    edited: boolean;
  }) => post<{ id: string }>("/api/medicines", body),

  /** Change dose times, course length or strength on a running course. */
  updateMedicine: (
    id: string,
    body: { dose_times: string[]; duration_days: number; strength?: string },
  ) =>
    patch<{
      id: string;
      dose_times: string[];
      duration_days: number;
      end_date: string;
      doses_removed: number;
      doses_created: number;
    }>(`/api/medicines/${id}`, body),

  /** Stop reminders but keep the history - what the reports are made of. */
  stopMedicine: (id: string) => del<{ stopped: boolean }>(`/api/medicines/${id}`),

  /** Delete outright, history and all. For a mistake, not for finishing. */
  deleteMedicine: (id: string) =>
    del<{ deleted: boolean; doses_removed: number }>(
      `/api/medicines/${id}?permanent=true`,
    ),

  whatsappStatus: () => get<WhatsAppStatus>("/api/whatsapp/status"),
};

// ------------------------------------------------------------- presentation

/** How each dose state should read and look on the dashboard. */
export const DOSE_LABELS: Record<DoseState, { label: string; tone: string }> = {
  SCHEDULED: { label: "Scheduled", tone: "muted" },
  SENT: { label: "Sent", tone: "info" },
  AWAITING_REPLY: { label: "Waiting for reply", tone: "info" },
  REMINDED_AGAIN: { label: "Reminded again", tone: "warn" },
  TAKEN: { label: "Taken", tone: "good" },
  TAKEN_LATE: { label: "Taken late", tone: "good-muted" },
  MISSED: { label: "Missed", tone: "bad" },
  SKIPPED: { label: "Skipped", tone: "muted" },
};
