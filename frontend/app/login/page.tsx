"use client";

/**
 * Caretaker sign-in and sign-up.
 *
 * Email and password, plus Google when the project has it switched on.
 *
 * The Google button is CONDITIONAL on the live provider list from
 * /auth/v1/settings, not always rendered. signInWithOAuth navigates the
 * browser away to Supabase, so when the provider is off there is no promise
 * left in our code to catch the failure - the caretaker just lands on a raw
 * JSON page reading {"code":400,...,"provider is not enabled"}. A button that
 * cannot work is worse than no button, so it only appears once it can.
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
  requestPasswordReset,
  resendSignupCode,
  signInWithEmail,
  signInWithGoogle,
  signUpWithEmail,
  verifySignupCode,
  type AuthSettings,
} from "@/lib/supabase";

/**
 * "in"     sign in
 * "up"     create an account
 * "verify" type the six-digit code we just emailed
 * "forgot" ask for a password reset link
 *
 * All four live on one screen. Signing up, confirming and resetting are one
 * continuous job for the person doing them, and sending them to another page
 * loses the email address they have already typed.
 */
type Mode = "in" | "up" | "verify" | "forgot";

const HEADING: Record<Mode, string> = {
  in: "Welcome back",
  up: "Create your caretaker account",
  verify: "Check your email",
  forgot: "Reset your password",
};

const SUBHEADING: Record<Mode, string> = {
  in: "Sign in to look after your family.",
  up: "Set up medicine reminders for someone you care about.",
  verify: "",
  forgot: "We'll email you a link to set a new one.",
};

const SUBMIT: Record<Mode, string> = {
  in: "Sign in",
  up: "Create account",
  verify: "Confirm and continue",
  forgot: "Email me a reset link",
};

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
  const [googleBusy, setGoogleBusy] = useState(false);
  const [code, setCode] = useState("");
  const [resending, setResending] = useState(false);

  useEffect(() => {
    getSession().then((s) => {
      if (s) router.replace("/dashboard");
    });
    getAuthSettings().then(setSettings);
  }, [router]);

  const needsEmailConfirmation = settings ? !settings.autoconfirm : false;
  /** Sign in and sign up are a choice; verify and forgot are steps within one. */
  const isChoice = mode === "in" || mode === "up";

  async function withGoogle() {
    setGoogleBusy(true);
    setError(null);
    setNotice(null);
    try {
      // On success this never returns - the browser leaves for Google.
      await signInWithGoogle();
    } catch (e) {
      setError((e as Error).message);
      setGoogleBusy(false);
    }
  }

  async function resend() {
    setResending(true);
    setError(null);
    try {
      await resendSignupCode(email);
      setNotice(`A new code is on its way to ${email}.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setResending(false);
    }
  }

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

        // Autoconfirm on means the account is usable immediately and
        // signUp already returned a session - no code, no waiting.
        const session = await getSession();
        if (session) {
          router.push("/dashboard");
          return;
        }
        setCode("");
        setMode("verify");
        setNotice(`We've emailed a six-digit code to ${email}.`);
      } else if (mode === "verify") {
        const session = await verifySignupCode(email, code);
        if (session) {
          router.push("/dashboard");
          return;
        }
        // Confirmed but no session: sign in with the password they just set.
        await signInWithEmail(email, password);
        router.push("/dashboard");
      } else if (mode === "forgot") {
        await requestPasswordReset(email);
        // Deliberately the same answer whether or not that address exists.
        setMode("in");
        setNotice(
          `If ${email} has an account, a reset link is on its way. ` +
            "It's good for one hour.",
        );
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
              hunt for sign-up inside a sentence. Hidden during verify and
              forgot: those are steps in a job already started, not a choice
              between two doors. */}
          {isChoice && (
            <div className="mb-6 grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
              <TabButton active={mode === "in"} onClick={() => switchTo("in")}>
                Sign in
              </TabButton>
              <TabButton active={mode === "up"} onClick={() => switchTo("up")}>
                Sign up
              </TabButton>
            </div>
          )}

          {!isChoice && (
            <button
              type="button"
              onClick={() => switchTo("in")}
              className="mb-4 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              &larr; Back to sign in
            </button>
          )}

          <h2 className="text-lg font-medium">{HEADING[mode]}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "verify"
              ? `Enter the six digits we sent to ${email}.`
              : SUBHEADING[mode]}
          </p>

          {!authConfigured && (
            <p className="mt-4 rounded-lg bg-late-soft p-3 text-sm text-late">
              Supabase isn&apos;t configured. Add NEXT_PUBLIC_SUPABASE_URL and
              NEXT_PUBLIC_SUPABASE_ANON_KEY to frontend/.env.local.
            </p>
          )}

          {settings?.providers.google && isChoice && (
            <>
              <button
                type="button"
                onClick={withGoogle}
                disabled={googleBusy || busy}
                className="mt-5 flex w-full items-center justify-center gap-2.5 rounded-md border
                           border-input bg-card px-4 py-2.5 text-sm font-medium
                           transition-colors hover:bg-muted
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
                           focus-visible:ring-offset-2 disabled:opacity-60"
              >
                <GoogleMark />
                {googleBusy
                  ? "Taking you to Google…"
                  : mode === "in"
                    ? "Sign in with Google"
                    : "Sign up with Google"}
              </button>

              <div className="my-5 flex items-center gap-3">
                <span className="h-px flex-1 bg-border" />
                <span className="text-xs text-muted-foreground">or use email</span>
                <span className="h-px flex-1 bg-border" />
              </div>
            </>
          )}

          <form onSubmit={submit} className={settings?.providers.google && isChoice ? "space-y-4" : "mt-5 space-y-4"}>
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

            {mode === "verify" && (
              <div className="space-y-1.5">
                <Label htmlFor="code">Confirmation code</Label>
                <Input
                  id="code"
                  value={code}
                  onChange={(e) =>
                    setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                  }
                  placeholder="123456"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                  autoFocus
                  className="text-center font-mono text-2xl tracking-[0.4em]"
                />
                <button
                  type="button"
                  onClick={resend}
                  disabled={resending}
                  className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline disabled:opacity-60"
                >
                  {resending ? "Sending…" : "Didn't get it? Send another"}
                </button>
              </div>
            )}

            {mode !== "verify" && (
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
            )}

            {mode !== "forgot" && mode !== "verify" && (
            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <Label htmlFor="password">Password</Label>
                {mode === "in" && authConfigured && (
                  <button
                    type="button"
                    onClick={() => switchTo("forgot")}
                    className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                  >
                    Forgot password?
                  </button>
                )}
              </div>
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
            )}

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
                We&apos;ll email you a six-digit code to confirm this address, so
                use a real one.
              </p>
            )}

            <Button type="submit" className="w-full" disabled={busy || !authConfigured}>
              {busy ? "Please wait…" : SUBMIT[mode]}
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

/**
 * Google's four-colour G, inline.
 *
 * Drawn here rather than fetched: the artwork is fixed, and an <img> to a CDN
 * is one more thing that can be slow or blocked on the morning of a demo.
 * These are Google's own brand hex values and must not be re-tinted.
 */
function GoogleMark() {
  return (
    <svg width="17" height="17" viewBox="0 0 48 48" aria-hidden focusable="false">
      <path
        fill="#4285F4"
        d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.69 28.18C11.25 26.86 11 25.45 11 24s.25-2.86.69-4.18v-5.7H4.34C2.85 17.09 2 20.45 2 24s.85 6.91 2.34 9.88l7.35-5.7z"
      />
      <path
        fill="#EA4335"
        d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"
      />
    </svg>
  );
}
