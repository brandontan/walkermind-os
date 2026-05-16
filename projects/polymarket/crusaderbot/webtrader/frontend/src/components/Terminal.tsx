import type { ReactNode } from "react";

export type TerminalPart =
  | { type: "cmd"; text: string }
  | { type: "ok"; text: string }
  | { type: "warn"; text: string }
  | { type: "out"; text: string }
  | { type: "dim"; text: string };

export type TerminalLine = {
  prompt?: string;
  parts: TerminalPart[];
  /** Show blinking cursor at the end of this line. */
  cursor?: boolean;
};

type Props = {
  title?: string;
  status?: "running" | "idle" | "error";
  lines: TerminalLine[];
};

const TONE: Record<TerminalPart["type"], string> = {
  cmd:  "text-cyan",
  ok:   "text-grn",
  warn: "text-gold",
  out:  "text-ink-2",
  dim:  "text-ink-3",
};

const STATUS_LABEL: Record<NonNullable<Props["status"]>, string> = {
  running: "RUNNING",
  idle:    "IDLE",
  error:   "ERROR",
};

const STATUS_COLOR: Record<NonNullable<Props["status"]>, string> = {
  running: "var(--grn,#00FF9C)",
  idle:    "var(--ink-3,#455370)",
  error:   "var(--red,#FF2D55)",
};

export function Terminal({ title = "scanner@crusaderbot", status = "running", lines }: Props) {
  const dotColor = STATUS_COLOR[status];
  return (
    <div
      className="relative mb-3 overflow-hidden clip-term bg-surface border border-border-2"
    >
      <span
        className="absolute top-0 left-0 w-full h-px pointer-events-none"
        style={{ background: "linear-gradient(90deg, var(--gold,#F5C842), transparent)" }}
        aria-hidden
      />
      <div
        className="flex items-center gap-2.5 py-2.5 px-3.5 border-b border-border-1"
        style={{ background: "rgba(245,200,66,0.025)" }}
      >
        <div className="flex gap-[5px]">
          <span className="w-[7px] h-[7px] rounded-full bg-red"
            style={{ boxShadow: "0 0 4px var(--red,#FF2D55)" }} aria-hidden />
          <span className="w-[7px] h-[7px] rounded-full bg-gold"
            style={{ boxShadow: "0 0 4px var(--gold,#F5C842)" }} aria-hidden />
          <span className="w-[7px] h-[7px] rounded-full bg-grn"
            style={{ boxShadow: "0 0 4px var(--grn,#00FF9C)" }} aria-hidden />
        </div>
        <span className="font-mono text-[10px] text-ink-3 tracking-[1px]">{title}</span>
        <span
          className="ml-auto font-mono text-[8px] font-bold tracking-[1.5px] flex items-center gap-1.5"
          style={{ color: dotColor }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full animate-status-pulse"
            style={{ background: dotColor, boxShadow: `0 0 6px ${dotColor}` }}
            aria-hidden
          />
          {STATUS_LABEL[status]}
        </span>
      </div>
      <div className="py-3 px-3.5 font-mono text-[11px] text-ink-2 leading-[1.7]">
        {lines.map((line, i) => (
          <div key={i} className="flex gap-2 items-baseline">
            <span className="text-gold flex-shrink-0 select-none">{line.prompt ?? "›"}</span>
            <span>
              {line.parts.map((p, j) => (
                <span key={j} className={TONE[p.type]}>
                  {p.text}
                </span>
              ))}
              {line.cursor && (
                <span
                  className="inline-block w-[7px] h-3 bg-gold align-middle ml-1 animate-blink"
                  aria-hidden
                />
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Convenience helper to build a t-line from a tagged template. */
export function line(prompt: string | undefined, parts: TerminalPart[], cursor?: boolean): TerminalLine {
  return { prompt, parts, cursor };
}

export type { ReactNode };
