import type { ReactNode } from "react";
import { AdvancedOnly } from "./AdvancedGate";

export type PositionSide = "yes" | "no" | "exp" | "credit" | "debit";

type Props = {
  market: string;
  positionValue: { value: string; tone: "zero" | "up" | "dn" };
  side: PositionSide;
  /** Primary meta items shown in essential + advanced. */
  meta: ReactNode[];
  /** Extra meta only shown in Advanced Mode (e.g. "YES @ 4.0¢", tx hashes). */
  metaAdvanced?: ReactNode[];
  onClick?: () => void;
};

const SIDE_LABEL: Record<PositionSide, string> = {
  yes:    "YES",
  no:     "NO",
  exp:    "EXPIRED",
  credit: "CREDIT",
  debit:  "DEBIT",
};

const SIDE_CLASS: Record<PositionSide, string> = {
  yes:    "bg-grn-2 text-grn",
  no:     "bg-red-2 text-red",
  exp:    "text-ink-3",
  credit: "bg-grn-2 text-grn",
  debit:  "text-ink-3",
};

const STRIPE: Record<PositionSide, string> = {
  yes:    "var(--grn,#00FF9C)",
  no:     "var(--red,#FF2D55)",
  exp:    "var(--ink-3,#455370)",
  credit: "var(--grn,#00FF9C)",
  debit:  "var(--ink-3,#455370)",
};

const PNL_TONE = {
  zero: "text-ink-2",
  up:   "text-grn",
  dn:   "text-red",
} as const;

export function PositionCard({ market, positionValue, side, meta, metaAdvanced, onClick }: Props) {
  return (
    <div
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick(); } : undefined}
      className={`relative mb-1.5 bg-surface border border-border-1 py-3 px-3.5 clip-pos transition-colors hover:border-border-3 ${
        onClick ? "cursor-pointer" : ""
      }`}
    >
      <span
        className="absolute left-0 top-0 bottom-0 w-0.5 opacity-70"
        style={{ background: STRIPE[side] }}
        aria-hidden
      />
      <div className="flex justify-between gap-2.5 mb-2">
        <div className="font-sans text-[13px] font-semibold leading-[1.3] text-ink-1 flex-1">
          {market}
        </div>
        <div className={`font-mono text-[13px] font-bold whitespace-nowrap ${PNL_TONE[positionValue.tone]}`}>
          {positionValue.value}
        </div>
      </div>
      <div className="flex gap-3 items-center font-mono text-[10px] text-ink-3 tracking-[0.5px]">
        <span
          className={`inline-flex items-center gap-1 py-0.5 px-[7px] text-[9px] font-bold tracking-[2px] rounded-sm ${
            side === "exp" || side === "debit"
              ? ""
              : ""
          } ${SIDE_CLASS[side]}`}
          style={
            side === "exp" || side === "debit"
              ? { background: "rgba(69,83,112,0.15)" }
              : undefined
          }
        >
          {SIDE_LABEL[side]}
        </span>
        <div className="flex gap-2.5 ml-auto">
          {meta.map((m, i) => (
            <span key={i} className="pos-meta-cell">
              {m}
            </span>
          ))}
          {metaAdvanced && metaAdvanced.length > 0 && (
            <AdvancedOnly>
              {metaAdvanced.map((m, i) => (
                <span key={`adv-${i}`} className="pos-meta-cell">
                  {m}
                </span>
              ))}
            </AdvancedOnly>
          )}
        </div>
      </div>
    </div>
  );
}
