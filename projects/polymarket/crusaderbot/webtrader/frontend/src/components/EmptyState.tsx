import type { ReactNode } from "react";

type Props = {
  icon?: ReactNode;
  title: string;
  text?: ReactNode;
};

export function EmptyState({ icon, title, text }: Props) {
  return (
    <div
      className="mb-3 px-5 py-8 text-center clip-card bg-surface border border-border-1"
    >
      {typeof icon === "string" && !icon.startsWith("<") && icon.trim().length <= 2 ? (
        <div className="text-[28px] mb-2 opacity-40">{icon}</div>
      ) : icon ? (
        <div className="flex justify-center mb-2 text-ink-4 opacity-40">{icon}</div>
      ) : (
        <div className="flex justify-center mb-2 text-ink-4 opacity-35">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18"/><circle cx="9" cy="9" r="0.5" fill="currentColor"/><circle cx="15" cy="9" r="0.5" fill="currentColor"/><path d="M9 15s1.5 2 3 2 3-2 3-2"/></svg>
        </div>
      )}
      <div className="font-hud text-[11px] font-bold tracking-[2px] text-ink-2 uppercase mb-1.5">
        {title}
      </div>
      {text && <div className="text-[12px] text-ink-3 leading-[1.5]">{text}</div>}
    </div>
  );
}
