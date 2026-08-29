/**
 * Supabase Auth client.
 *
 * The browser signs in here; the resulting JWT is sent to our FastAPI backend,
 * which verifies it against Supabase's public JWKS. The database itself is
 * never touched from the browser - every read and write goes through our API,
 * so the ownership rules live in one place.
 */

import { createClient, type Session } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

/** False when Supabase is not configured, so the UI can explain rather than crash. */
export const authConfigured = Boolean(url && anonKey);

export const supabase = createClient(url || "https://placeholder.supabase.co", anonKey || "placeholder", {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

export async function getSession(): Promise<Session | null> {
  if (!authConfigured) return null;
  const { data } = await supabase.auth.getSession();
  return data.session;
}

export async function signInWithEmail(email: string, password: string) {
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw new Error(friendly(error.message));
}

export async function signUpWithEmail(email: string, password: string, name: string) {
  const { error } = await supabase.auth.signUp({
    email,
    password,
    options: { data: { full_name: name } },
  });
  if (error) throw new Error(friendly(error.message));
}

/**
 * Confirm a new account with the six-digit code from the email.
 *
 * A code rather than a link, deliberately. A caretaker signing up on their
 * phone gets an email whose link opens whichever browser their mail app
 * prefers - often not the one holding the half-finished sign-up - and the
 * session lands in the wrong place. A code is typed back into the page they
 * are already looking at.
 *
 * Succeeding here returns a live session, so the caller can go straight to
 * the dashboard rather than asking them to sign in again with the password
 * they typed ninety seconds ago.
 */
export async function verifySignupCode(email: string, code: string) {
  const { data, error } = await supabase.auth.verifyOtp({
    email,
    token: code.trim(),
    type: "signup",
  });
  if (error) throw new Error(friendly(error.message));
  return data.session;
}

/** Send the confirmation code again. Supabase rate-limits this; say so. */
export async function resendSignupCode(email: string) {
  const { error } = await supabase.auth.resend({ type: "signup", email });
  if (error) throw new Error(friendly(error.message));
}

/**
 * Start a password reset. Always resolves, even for an unknown address.
 *
 * Supabase deliberately does not say whether an account exists, and neither
 * do we: "if that address has an account, a link is on its way" tells a
 * legitimate user everything they need and tells someone probing for
 * registered addresses nothing.
 */
export async function requestPasswordReset(email: string) {
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${window.location.origin}/reset-password`,
  });
  if (error) throw new Error(friendly(error.message));
}

/**
 * Set a new password. Only works while a recovery session is open - which is
 * what the emailed link creates, via detectSessionInUrl above.
 */
export async function updatePassword(password: string) {
  const { error } = await supabase.auth.updateUser({ password });
  if (error) throw new Error(friendly(error.message));
}

/**
 * Which sign-in methods this Supabase project actually has switched on.
 *
 * Worth asking, because signInWithOAuth NAVIGATES the browser to Supabase. If
 * the provider is off, Supabase answers with a raw JSON error page and there
 * is no promise left in our code to catch it - the user just sees
 * {"code":400,...,"provider is not enabled"}. Checking first is the only way
 * to fail politely.
 */
export type AuthSettings = {
  providers: Record<string, boolean>;
  /** True when a new account can sign in immediately, with no email link. */
  autoconfirm: boolean;
};

let settingsCache: AuthSettings | null = null;

export async function getAuthSettings(): Promise<AuthSettings> {
  if (settingsCache) return settingsCache;
  const fallback: AuthSettings = { providers: { email: true }, autoconfirm: true };
  if (!authConfigured) return fallback;

  try {
    const res = await fetch(`${url}/auth/v1/settings`, { headers: { apikey: anonKey } });
    if (!res.ok) return fallback;
    const data = await res.json();
    settingsCache = {
      providers: (data.external ?? {}) as Record<string, boolean>,
      autoconfirm: Boolean(data.mailer_autoconfirm),
    };
    return settingsCache;
  } catch {
    return fallback;
  }
}

export async function signInWithGoogle() {
  const settings = await getAuthSettings();
  if (!settings.providers.google) {
    throw new Error(
      "Google sign-in isn't switched on for this project yet. Use email and " +
        "password below, or enable it in Supabase → Authentication → " +
        "Sign In / Providers → Google.",
    );
  }

  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${window.location.origin}/dashboard` },
  });
  if (error) throw new Error(friendly(error.message));
}

export async function signOut() {
  await supabase.auth.signOut();
}

/** Supabase's errors are terse. Say what to actually do about them. */
function friendly(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("invalid login")) return "That email and password don't match.";
  if (m.includes("already registered")) return "That email already has an account — sign in instead.";
  if (m.includes("password should be")) return "Password needs to be at least 6 characters.";
  if (m.includes("provider is not enabled"))
    return "Google sign-in isn't enabled yet. Turn it on in Supabase → Authentication → Providers, or use email instead.";
  if (m.includes("email not confirmed"))
    return "This account still needs confirming. Check your email for the code we sent.";
  if (m.includes("token has expired") || m.includes("expired"))
    return "That code has expired. Ask for a new one.";
  if (m.includes("invalid") && m.includes("token"))
    return "That code isn't right. Check the email again — it's six digits.";
  if (m.includes("otp_expired")) return "That code has expired. Ask for a new one.";
  if (m.includes("for security purposes") || m.includes("rate limit") ||
      m.includes("too many"))
    return "That was a lot of tries in a row. Wait a minute, then try again.";
  if (m.includes("same password"))
    return "That's the password you already have — pick a different one.";
  if (m.includes("auth session missing") || m.includes("session_not_found"))
    return "This reset link has expired. Ask for a new one from the sign-in page.";
  return message;
}
