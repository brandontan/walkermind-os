import type { ReactNode } from "react";

type Props = {
  title: ReactNode;
  subtitle: string;
  right?: ReactNode;
};

export function DesktopPageHeader({ title, subtitle, right }: Props) {
  return (
    <div
      className="hidden md:flex items-center justify-between pb-5 mb-6"
      style={{ borderBottom: "1px solid rgba(245,200,66,0.06)" }}
    >
      <div>
        <div className="font-display text-[30px] tracking-[1px] uppercase leading-none text-ink-1">
          {title}
        </div>
        <div className="font-mono text-[9px] text-ink-3 tracking-[2px] uppercase mt-[5px]">
          {subtitle}
        </div>
      </div>
      {right && <div>{right}</div>}
    </div>
  );
}
