import type { ReactNode } from "react";

type GroupProps = {
  title: string;
  children: ReactNode;
};

export function SettingsGroup({ title, children }: GroupProps) {
  return (
    <div className="mb-3 bg-surface border border-border-1 clip-card overflow-hidden">
      <div
        className="py-2.5 px-3.5 font-hud text-[9px] font-bold tracking-[2.5px] text-gold uppercase border-b border-border-1"
        style={{ background: "rgba(245,200,66,0.025)" }}
      >
        <span>◢ </span>{title}
      </div>
      {children}
    </div>
  );
}

type RowProps = {
  name: ReactNode;
  desc?: ReactNode;
  /** Right-side control (Toggle, value, status pill, etc.). */
  control: ReactNode;
  /** When true, name is rendered with Orbitron headline styling. */
  emphasis?: boolean;
};

export function SettingsRow({ name, desc, control, emphasis = false }: RowProps) {
  return (
    <div className="py-3 px-3.5 flex items-center justify-between gap-2.5 border-b border-border-1 last:border-b-0">
      <div className="flex-1">
        <div
          className={
            emphasis
              ? "font-hud text-[12px] tracking-[1.5px] text-gold mb-0.5"
              : "text-[14px] font-semibold text-ink-1 mb-0.5"
          }
        >
          {name}
        </div>
        {desc && <div className="text-[11px] text-ink-3 font-sans">{desc}</div>}
      </div>
      <div className="font-mono text-[11px] text-ink-2 tracking-[0.5px]">{control}</div>
    </div>
  );
}
