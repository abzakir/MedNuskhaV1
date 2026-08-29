"use client";

/**
 * Where the "reset your password" email lands.
 *
 * Supabase puts a recovery token in the URL fragment; the client is created
 * with detectSessionInUrl, so supabase-js swaps it for a short-lived session
 * before this component ever renders. That session can do exactly one useful
 * thing - change the password - which is why there is no old-password field:
 * possession of the emailed link is the proof.
 *
 * The link is single-use and expires in an hour, so the common failure here
 * is an old link, not a wrong password. That case gets its own explanation
 * and a way back rather than a raw Supabase error.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getSession, supabase, updatePassword } from "@/lib/supabase";

type State = "checking" | "ready" | "expired" | "done";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [state, setState] = useState<State>("checking");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    // The session may not exist yet on first paint: supabase-js reads the URL
    // fragment asynchronously. Listen as well as look, so a link that works
    // is not reported as expired a few milliseconds too early.
    const { data: sub } = supabase.auth.onAuthStateChange((event) => {
      if (!alive) return;
      if (event === "PASSWORD_RECOVERY" || event === "SIGNED_IN") setState("ready");
    });

    const timer = setTimeout(async () => {
      if (!alive) return;
      const session = await getSession();
      setState((current) =>
        current === "checking" ? (session ? "ready" : "expired") : current,
      );
    }, 1200);

    return () => {
      alive = false;
      clearTimeout(timer);
      sub.subscription.unsubscribe();
    };
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirm) {
      setError("Those two passwords don't match.");
      return;
    }

    setBusy(true);
    try {
      await updatePassword(password);
      setState("done");
      setTimeout(() => router.replace("/dashboard"), 1600);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-paper p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-display text-5xl leading-none tracking-tight text-primary">
            MedNuskha
          </h1>
        </div>

        <div className="rounded-xl border bg-card p-6 shadow-lift">
          {state === "checking" && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Checking your link&hellip;
            </p>
          )}

          {state === "expired" && (
            <>
              <h2 className="text-lg font-medium">This link has expired</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Reset links last an hour and work once. Ask for a fresh one and
                it&apos;ll be in your inbox in a moment.
              </p>
              <Button asChild className="mt-5 w-full">
                <Link href="/login">Back to sign in</Link>
              </Button>
            </>
          )}

          {state === "done" && (
            <>
              <h2 className="text-lg font-medium text-taken">Password changed</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                You&apos;re signed in. Taking you to your dashboard&hellip;
              </p>
            </>
          )}

          {state === "ready" && (
            <>
              <h2 className="text-lg font-medium">Choose a new password</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                You&apos;ll be signed in straight after.
              </p>

              <form onSubmit={submit} className="mt-5 space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="password">New password</Label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="At least 6 characters"
                    required
                    minLength={6}
                    autoFocus
                    autoComplete="new-password"
                  />
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="confirm">Type it again</Label>
                  <Input
                    id="confirm"
                    type="password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                    minLength={6}
                    autoComplete="new-password"
                  />
                </div>

                {error && (
                  <p className="rounded-lg bg-missed-soft p-3 text-sm text-missed">
                    {error}
                  </p>
                )}

                <Button type="submit" className="w-full" disabled={busy}>
                  {busy ? "Saving…" : "Save new password"}
                </Button>
              </form>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
