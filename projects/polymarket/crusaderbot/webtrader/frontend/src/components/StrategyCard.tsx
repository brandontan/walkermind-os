type Risk = "safe" | "balanced" | "aggressive";

interface StrategyCardProps {
  preset_key:  string;
  name:        string;
  description: string;
  risk:        Risk;
  tp_pct:      number;
  sl_pct:      number;
  capital_pct: number;
  isActive:    boolean;
  onActivate:  (key: string) => void;
}

const NAME_TONE: Record<Risk, string> = {
  safe:       "text-grn",
  balanced:   "text-gold",
  aggressive: "text-red",
};

export function StrategyCard({
  preset_key, name, description, risk,
  tp_pct, sl_pct, capital_pct,
  isActive, onActivate,
}: StrategyCardProps) {
  return (
    <button
      type="button"
      onClick={() => onActivate(preset_key)}
      className={`relative w-full text-left mb-2 p-4 clip-card-lg cursor-pointer transition-all border ${
        isActive ? "border-gold" : "border-border-1 hover:border-border-3"
      }`}
      style={
        isActive
          ? {
              background:
                "linear-gradient(135deg, rgba(245,200,66,0.05) 0%, var(--surface,#0D1322) 50%)",
            }
          : { background: "var(--surface,#0D1322)" }
      }
    >
      {isActive && (
        <span
          className="absolute top-0 left-0 w-full h-0.5 bg-gold pointer-events-none"
          style={{ boxShadow: "0 0 12px var(--gold,#F5C842)" }}
          aria-hidden
        />
      )}
      <div className="flex justify-between items-start mb-2.5">
        <div className={`font-display text-[22px] leading-none tracking-[0.5px] uppercase ${NAME_TONE[risk]}`}>
          {name}
        </div>
        {isActive && (
          <span className="font-mono text-[9px] font-bold tracking-[2px] text-gold inline-flex items-center gap-1">
            <span
              className="w-1.5 h-1.5 rounded-full bg-grn"
              style={{ boxShadow: "0 0 8px var(--grn,#00FF9C)" }}
              aria-hidden
            />
            ACTIVE
          </span>
        )}
      </div>
      <p className="text-[13px] text-ink-2 leading-[1.4] mb-3">{description}</p>
      <div className="flex gap-3.5 font-mono text-[10px] text-ink-3 tracking-[0.5px]">
        <Stat label="Capital"     value={`≤ ${capital_pct}%`} />
        <Stat label="Take Profit" value={`+${tp_pct}%`} />
        <Stat label="Stop Loss"   value={`−${sl_pct}%`} />
      </div>
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span>{label}</span>
      <span className="text-ink-1 font-bold text-[11px]">{value}</span>
    </div>
  );
}
