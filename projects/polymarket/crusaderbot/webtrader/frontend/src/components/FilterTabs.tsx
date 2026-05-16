import { AdvancedOnly } from "./AdvancedGate";

export type FilterTab<K extends string> = {
  key: K;
  label: string;
  count?: number;
  /** When true, this tab is only visible in Advanced Mode. */
  advanced?: boolean;
};

type Props<K extends string> = {
  tabs: FilterTab<K>[];
  active: K;
  onChange: (key: K) => void;
};

export function FilterTabs<K extends string>({ tabs, active, onChange }: Props<K>) {
  return (
    <div className="flex gap-1 mb-3 bg-surface p-1 border border-border-1 clip-card-sm">
      {tabs.map((tab) => {
        const node = (
          <button
            type="button"
            key={tab.key}
            onClick={() => onChange(tab.key)}
            className={`flex-1 py-[7px] px-2.5 font-hud text-[10px] font-bold tracking-[1.5px] text-center cursor-pointer uppercase transition-colors ${
              active === tab.key
                ? "text-gold"
                : "text-ink-3 hover:text-ink-2"
            }`}
            style={
              active === tab.key
                ? {
                    background: "rgba(245,200,66,0.10)",
                    boxShadow: "inset 0 1px 0 var(--gold,#F5C842)",
                  }
                : undefined
            }
          >
            {tab.label}
            {typeof tab.count === "number" && <span className="opacity-70"> · {tab.count}</span>}
          </button>
        );
        return tab.advanced ? (
          <AdvancedOnly key={tab.key}>{node}</AdvancedOnly>
        ) : (
          node
        );
      })}
    </div>
  );
}
