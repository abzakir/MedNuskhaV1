import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Digits only, no + and no leading zero: 923001234567.
 *
 * This must agree exactly with `normalise_number` in
 * backend/app/whatsapp/client.py and `normalise` in whatsapp-bridge/index.js.
 * Where it did not, "0300 1234567" typed into the edit form was saved as
 * "3001234567" — a number long enough to pass validation and short of a
 * country code, so every reminder went nowhere.
 */
export function normalizeNumber(raw: string): string {
  let digits = (raw || "").replace(/\D/g, "");
  if (digits.startsWith("00")) digits = digits.slice(2);
  if (digits.startsWith("0")) digits = "92" + digits.replace(/^0+/, "");
  return digits;
}
