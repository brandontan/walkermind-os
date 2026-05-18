import { ReactNode, useState } from "react";

interface Props {
  id: string;
  label: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  action?: ReactNode;
}

const KEY = (id: string) => `cb_collapse_${id}`;

export function CollapsibleSection({
  id,
  label,
  children,
  defaultOpen = true,
  action,
}: Props) {
  const [open, setOpen] = useState(() => {
    try {
      const v = localStorage.getItem(KEY(id));
      return v !== null ? v === "1" : defaultOpen;
    } catch {
      return defaultOpen;
    }
  });

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(KEY(id), next ? "1" : "0");
      } catch {}
      return next;
    });
  };

  return (
    <div>
      <div className="flex items-center justify-between mt-3.5 mb-2 mx-0.5">
        <button
          type="button"
          onClick={toggle}
          className="flex items-center gap-2 cursor-pointer"
          aria-expanded={open}
        >
          <span className="w-3 h-px bg-gold flex-shrink-0" aria-hidden />
          <span className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase">
            {label}
          </span>
          <span
            className="text-ink-3 text-[10px] transition-transform duration-150 flex-shrink-0"
            style={{ display: "inline-block", transform: open ? "rotate(0deg)" : "rotate(-90deg)" }}
            aria-hidden
          >
            ▾
          </span>
        </button>
        {action && <div>{action}</div>}
      </div>
      <div style={{ display: open ? "block" : "none" }}>{children}</div>
    </div>
  );
}
