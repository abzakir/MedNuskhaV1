/**
 * The single place the dashboard talks to the FastAPI backend.
 *
 * Base URL comes from NEXT_PUBLIC_API_BASE (AGENTS.md section 13). In local
 * dev it is unset and falls back to the port `make dev` uses; on Vercel it is
 * set to the deployed backend's HTTPS URL (Phase 8).
 */

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

/** Fetch JSON from the backend. Throws ApiError on a non-2xx response. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });

  if (!res.ok) {
    throw new ApiError(`${init?.method ?? "GET"} ${path} failed`, res.status);
  }
  return (await res.json()) as T;
}

export type Health = {
  status: string;
  service: string;
  version: string;
  timezone: string;
  database: string;
  whatsapp: string;
  missing_env: string[];
};

export const getHealth = () => api<Health>("/api/health");
