import { DOSE_LABELS, type DoseState } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Dose state, encoded in colour AND in shape.
 *
 * Colour alone is not enough here: this gets shown on a projector, and one in
 * twelve men cannot reliably separate the taken green from the missed red. So
 * each state also carries a distinct mark - a filled dot, a ring, a slash -
 * and the live states carry motion nothing else has.
 */

const TONES: Record<string, { pill: string; mark: string }> = {
  good: {
    pill: "bg-taken-soft text-taken ring-taken/25",
    mark: "bg-current",
  },
  "good-muted": {
    pill: "bg-late-soft text-late ring-late/25",
    mark: "bg-current",
  },
  bad: {
    pill: "bg-missed-soft text-missed ring-missed/25",
    mark: "bg-current",
  },
  warn: {
    pill: "bg-late-soft text-late ring-late/25",
    mark: "bg-current",
  },
  info: {
    pill: "bg-live-soft text-live ring-live/25",
    mark: "bg-current",
  },
  muted: {
    pill: "bg-pending-soft text-muted-foreground ring-border",
    mark: "bg-current",
  },
};

const LIVE_STATES: DoseState[] = ["SENT", "AWAITING_REPLY", "REMINDED_AGAIN"];

export function StatusPill({ state }: { state: DoseState }) {
  const meta = DOSE_LABELS[state] ?? { label: state, tone: "muted" };
  const tone = TONES[meta.tone] ?? TONES.muted;
  const live = LIVE_STATES.includes(state);
  const missed = state === "MISSED" || state === "SKIPPED";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5",
        "text-xs font-medium ring-1 ring-inset",
        tone.pill,
      )}
    >
      {live ? (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      ) : missed ? (
        // A hollow ring, so "missed" reads as an empty box on the chart even
        // when the colour does not carry.
        <span className="h-1.5 w-1.5 rounded-full border border-current" />
      ) : (
        <span className={cn("h-1.5 w-1.5 rounded-full", tone.mark)} />
      )}
      {meta.label}
    </span>
  );
}

/**
 * The one number the caretaker came for. Set in the display serif at large
 * sizes, because at 48px a grotesque digit is just a digit and this is the
 * headline of the page.
 */
export function AdherenceNumber({
  percent,
  size = "md",
}: {
  percent: number | null;
  size?: "sm" | "md" | "lg";
}) {
  const sizes = {
    sm: "text-2xl",
    md: "text-4xl",
    lg: "text-6xl",
  };

  if (percent === null) {
    return (
      <span
        className={cn(sizes[size], "font-display leading-none text-muted-foreground")}
        title="Nothing has been answered yet"
      >
        &mdash;
      </span>
    );
  }

  const tone =
    percent >= 85 ? "text-taken" : percent >= 60 ? "text-late" : "text-missed";

  return (
    <span className={cn(sizes[size], "font-display leading-none tnum", tone)}>
      {percent}
      <span className="ml-0.5 align-top text-[0.36em] font-sans font-medium tracking-label">
        %
      </span>
    </span>
  );
}
