"use client";

/**
 * Caretaker sign-in and sign-up.
 *
 * Email and password only. Google was deliberately dropped for the hackathon:
 * it needs a Google Cloud OAuth client, and the sign-in method is not what the
 * product is being judged on. The provider check in lib/supabase.ts remains,
 * so switching it back on later is a Supabase setting rather than a code
 * change.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  authConfigured,
  getAuthSettings,
  getSession,
  signInWithEmail,
  signUpWithEmail,
  type AuthSettings,
} from "@/lib/supabase";

type Mode = "in" | "up";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("in");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [settings, setSettings] = useState<AuthSettings | null>(null);

  useEffect(() => {
    getSession().then((s) => {
      if (s) router.replace("/dashboard");
    });
    getAuthSettings().then(setSettings);
  }, [router]);

  const needsEmailConfirmation = settings ? !settings.autoconfirm : false;

  function switchTo(next: Mode) {
    setMode(next);
    setError(null);
    setNotice(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "up") {
        await signUpWithEmail(email, password, name);
        const session = await getSession();
        if (session) {
          router.push("/dashboard");
          return;
        }
        setNotice(
          "Account created. Check your inbox for the confirmation link, then sign in.",
        );
        setMode("in");
      } else {
        await signInWithEmail(email, password);
        router.push("/dashboard");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center bg-paper p-6">
      {/* The chart this replaces is ruled paper on a fridge door. Faint
          enough to be texture rather than decoration. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            "linear-gradient(to right, var(--border) 1px, transparent 1px)," +
            "linear-gradient(to bottom, var(--border) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
          maskImage:
            "radial-gradient(ellipse 80% 60% at 50% 40%, black 20%, transparent 75%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 80% 60% at 50% 40%, black 20%, transparent 75%)",
        }}
      />
      <div className="relative w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-display text-5xl leading-none tracking-tight text-primary">
            MedNuskha
          </h1>
          <p className="mx-auto mt-3 max-w-[30ch] text-sm leading-relaxed text-muted-foreground">
            Medicine reminders that reach your family on WhatsApp, in Urdu.
            Nothing for them to install, nothing to learn.
          </p>
        </div>

        <div className="rounded-xl border bg-card p-6 shadow-lift">
          {/* Both options visible at once - a new caretaker should not have to
              hunt for sign-up inside a sentence. */}
          <div className="mb-6 grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
            <TabButton active={mode === "in"} onClick={() => switchTo("in")}>
              Sign in
            </TabButton>
            <TabButton active={mode === "up"} onClick={() => switchTo("up")}>
              Sign up
            </TabButton>
          </div>

          <h2 className="text-lg font-medium">
            {mode === "in" ? "Welcome back" : "Create your caretaker account"}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "in"
              ? "Sign in to look after your family."
              : "Set up medicine reminders for someone you care about."}
          </p>

          {!authConfigured && (
            <p className="mt-4 rounded-lg bg-late-soft p-3 text-sm text-late">
              Supabase isn&apos;t configured. Add NEXT_PUBLIC_SUPABASE_URL and
              NEXT_PUBLIC_SUPABASE_ANON_KEY to frontend/.env.local.
            </p>
          )}

          <form onSubmit={submit} className="mt-5 space-y-4">
            {mode === "up" && (
              <div className="space-y-1.5">
                <Label htmlFor="name">Your name</Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Zakir"
                  required
                  autoFocus
                />
                <p className="text-xs text-muted-foreground">
                  Used in messages to your family member.
                </p>
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@gmail.com"
                required
                autoComplete="email"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 6 characters"
                required
                minLength={6}
                autoComplete={mode === "in" ? "current-password" : "new-password"}
              />
            </div>

            {error && (
              <p className="rounded-lg bg-missed-soft p-3 text-sm text-missed">
                {error}
              </p>
            )}
            {notice && (
              <p className="rounded-lg bg-taken-soft p-3 text-sm text-taken">
                {notice}
              </p>
            )}
            {mode === "up" && needsEmailConfirmation && (
              <p className="rounded-lg bg-live-soft p-3 text-xs text-live">
                This project requires email confirmation, so you&apos;ll get a link
                before you can sign in. Use a real address.
              </p>
            )}

            <Button type="submit" className="w-full" disabled={busy || !authConfigured}>
              {busy
                ? "Please wait…"
                : mode === "in"
                  ? "Sign in"
                  : "Create account"}
            </Button>
          </form>

          {mode === "in" && (
            <p className="mt-5 border-t pt-5 text-center text-sm text-muted-foreground">
              Looking after someone for the first time?{" "}
              <button
                type="button"
                className="font-medium text-taken underline-offset-4 hover:underline"
                onClick={() => switchTo("up")}
              >
                Create an account
              </button>
            </p>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Your family member never installs anything. Reminders arrive on WhatsApp.
        </p>
      </div>
    </main>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${ active
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}
