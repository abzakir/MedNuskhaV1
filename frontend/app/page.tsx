"use client";

/**
 * Phase 0 stub page.
 *
 * Its only job is to prove the two halves of `make dev` can see each other:
 * the dashboard renders and reaches GET /api/health. The real family overview
 * replaces this in Phase 4.
 */

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { API_BASE, getHealth, type Health } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "error"; message: string };

export default function Home() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    getHealth()
      .then((health) => setState({ kind: "ok", health }))
      .catch((err: Error) => setState({ kind: "error", message: err.message }));
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 p-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">MedNuskha</h1>
        <p className="text-muted-foreground">
          Medication adherence for elderly patients, over WhatsApp.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Backend</CardTitle>
          <CardDescription className="font-mono text-xs">{API_BASE}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {state.kind === "loading" && (
            <p className="text-muted-foreground">Checking…</p>
          )}

          {state.kind === "error" && (
            <div className="space-y-2">
              <Badge variant="destructive">unreachable</Badge>
              <p className="text-muted-foreground">
                {state.message}. Is the backend running on {API_BASE}?
              </p>
            </div>
          )}

          {state.kind === "ok" && (
            <dl className="grid grid-cols-[8rem_1fr] gap-y-2">
              <dt className="text-muted-foreground">Service</dt>
              <dd>
                <Badge>{state.health.status}</Badge>
              </dd>

              <dt className="text-muted-foreground">Database</dt>
              <dd>
                <Badge
                  variant={
                    state.health.database === "connected" ? "default" : "secondary"
                  }
                >
                  {state.health.database}
                </Badge>
              </dd>

              <dt className="text-muted-foreground">WhatsApp</dt>
              <dd>
                <Badge
                  variant={
                    state.health.whatsapp === "configured" ? "default" : "secondary"
                  }
                >
                  {state.health.whatsapp}
                </Badge>
              </dd>

              <dt className="text-muted-foreground">Timezone</dt>
              <dd className="font-mono text-xs">{state.health.timezone}</dd>

              {state.health.missing_env.length > 0 && (
                <>
                  <dt className="text-muted-foreground">Missing env</dt>
                  <dd className="font-mono text-xs">
                    {state.health.missing_env.join(", ")}
                  </dd>
                </>
              )}
            </dl>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Phase 0 — bootstrap. The family overview lands in Phase 4.
      </p>
    </main>
  );
}
