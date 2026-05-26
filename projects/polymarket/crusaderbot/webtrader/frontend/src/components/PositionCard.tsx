import { useState, type ReactNode } from "react";
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
  /** Override the left border color with a P&L tone instead of side color. */
  borderTone?: "up" | "dn" | "zero";
  /** Optional footer rendered below the meta row (e.g. Cash Out button). */
  footer?: ReactNode;
  /** Optional expandable detail panel (entry/exit/SL/TP). Tap the card to toggle. */
  detail?: ReactNode;
  onClick?: () => void;
  defaultExpanded?: boolean;
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

const STRIPE_TONE: Record<"up" | "dn" | "zero", string> = {
  up:   "var(--grn,#00FF9C)",
  dn:   "var(--red,#FF2D55)",
  zero: "var(--ink-3,#455370)",
};

const PNL_TONE = {
  zero: "text-ink-2",
  up:   "text-grn",
  dn:   "text-red",
} as const;

export function PositionCard({ market, positionValue, side, meta, metaAdvanced, borderTone, footer, detail, onClick, defaultExpanded }: Props) {
  const stripeColor = borderTone ? STRIPE_TONE[borderTone] : STRIPE[side];
  const [expanded, setExpanded] = useState(defaultExpanded ?? false);
  const expandable = !!detail;
  const toggle = () => setExpanded((v) => !v);
  const interactive = onClick ?? (expandable ? toggle : undefined);
  return (
    <div
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive}
      onKeyDown={interactive ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); interactive(); } } : undefined}
      aria-expanded={expandable ? expanded : undefined}
      className={`relative mb-1.5 bg-surface border border-border-1 py-3 px-3.5 clip-pos transition-colors hover:border-border-3 ${
        interactive ? "cursor-pointer" : ""
      }`}
    >
      <span
        className="absolute left-0 top-0 bottom-0 w-0.5 opacity-70"
        style={{ background: stripeColor }}
        aria-hidden
      />
      <div className="flex justify-between gap-2.5 mb-2">
        <div className="font-sans text-[13px] font-semibold leading-[1.3] text-ink-1 flex-1 min-w-0 truncate">
          {market}
        </div>
        <div className="flex items-center gap-1.5 whitespace-nowrap">
          <div className={`font-mono text-[13px] font-bold ${PNL_TONE[positionValue.tone]}`}>
            {positionValue.value}
          </div>
          {expandable && (
            <span className={`text-ink-3 text-[10px] transition-transform ${expanded ? "rotate-180" : ""}`} aria-hidden>
              ▾
            </span>
          )}
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
      {expandable && expanded && (
        <div className="mt-2 pt-2 border-t border-border-1" onClick={(e) => e.stopPropagation()}>
          {detail}
        </div>
      )}
      {footer && <div className="mt-1 px-0" onClick={(e) => e.stopPropagation()}>{footer}</div>}
    </div>
  );
}
