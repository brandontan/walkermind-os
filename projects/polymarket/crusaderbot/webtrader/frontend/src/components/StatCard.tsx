import type { ReactNode } from "react";

export type StatColor = "grn" | "gold" | "cyan" | "blue" | "red";

type Props = {
  label: string;
  value: ReactNode;
  /** Optional unit shown smaller next to the value (e.g. "USDC"). */
  unit?: string;
  /** Sub-line under the value (e.g. "Paper · Polygon · Tier 3"). */
  sub?: ReactNode;
  /** Sub-line accent. */
  subTone?: "neutral" | "up" | "dn";
  /** Color of the top accent bar + value tint. */
  color?: StatColor;
  /** Large variant — spans 2 rows in asymmetric grid, bigger value font. */
  large?: boolean;
  /** Small icon glyph before label. */
  icon?: ReactNode;
};

const BAR_COLOR: Record<StatColor, string> = {
  grn:  "#00FF9C",
  gold: "#F5C842",
  cyan: "#00E5FF",
  blue: "#4D9FFF",
  red:  "#FF2D55",
};

const VAL_TONE: Record<StatColor, string> = {
  grn:  "text-grn",
  gold: "text-gold",
  cyan: "text-cyan",
  blue: "text-blue",
  red:  "text-red",
};

export function StatCard({
  label,
  value,
  unit,
  sub,
  subTone = "neutral",
  color = "gold",
  large = false,
  icon,
}: Props) {
  const bar = BAR_COLOR[color];
  return (
    <div
      className={`relative overflow-hidden clip-card bg-surface border border-border-1 transition-colors hover:border-border-3 ${
        large ? "row-span-2 p-[16px_14px_14px]" : "p-[12px_12px_11px]"
      }`}
    >
      <span
        className="absolute top-0 left-0 h-0.5 w-7"
        style={{ background: bar, boxShadow: `0 0 12px ${bar}` }}
        aria-hidden
      />
      <div
        className={`font-mono text-[9px] font-bold tracking-[2px] text-ink-3 uppercase flex items-center gap-1.5 ${
          large ? "mb-2.5" : "mb-2"
        }`}
      >
        {icon && <span className="text-gold text-[11px]">{icon}</span>}
        {label}
      </div>
      <div
        className={`font-display leading-none tracking-[-0.5px] ${VAL_TONE[color]}`}
        style={{ fontSize: large ? "36px" : "24px" }}
      >
        {value}
        {unit && (
          <span className="opacity-60 ml-0.5" style={{ fontSize: "0.5em", letterSpacing: "1px" }}>
            {unit}
          </span>
        )}
      </div>
      {sub && (
        <div
          className={`font-mono text-[9px] tracking-[0.5px] mt-1 ${
            subTone === "up" ? "text-grn opacity-70" : subTone === "dn" ? "text-red opacity-70" : "text-ink-3"
          }`}
        >
          {sub}
        </div>
      )}
    </div>
  );
}
