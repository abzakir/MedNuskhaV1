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

export async function signInWithGoogle() {
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
    return "Check your email for the confirmation link, or disable email confirmation in Supabase → Authentication → Providers → Email.";
  return message;
}
