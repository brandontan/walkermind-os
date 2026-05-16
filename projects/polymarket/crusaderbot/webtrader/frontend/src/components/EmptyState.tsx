import type { ReactNode } from "react";

type Props = {
  icon?: ReactNode;
  title: string;
  text?: ReactNode;
};

export function EmptyState({ icon = "📭", title, text }: Props) {
  return (
    <div
      className="mb-3 px-5 py-8 text-center clip-card bg-surface border border-dashed border-border-2"
    >
      <div className="text-[32px] mb-2 opacity-50">{icon}</div>
      <div className="font-hud text-[11px] font-bold tracking-[2px] text-ink-2 uppercase mb-1.5">
        {title}
      </div>
      {text && <div className="text-[12px] text-ink-3 leading-[1.5]">{text}</div>}
    </div>
  );
}
