interface StrategyCardProps {
  name:        string;
  preset_key:  string;
  emoji:       string;
  description: string;
  risk:        "safe" | "balanced" | "aggressive";
  tp_pct:      number;
  sl_pct:      number;
  capital_pct: number;
  freq:        string;
  isActive:    boolean;
  onActivate:  (key: string) => void;
}

const RISK_BADGE: Record<string, { label: string; color: string }> = {
  safe:       { label: "SAFE",     color: "text-green bg-green/10 border-green/30" },
  balanced:   { label: "BALANCED", color: "text-gold  bg-gold/10  border-gold/30"  },
  aggressive: { label: "HIGH",     color: "text-red   bg-red/10   border-red/30"   },
};

export function StrategyCard({
  name, preset_key, emoji, description, risk,
  tp_pct, sl_pct, capital_pct, freq,
  isActive, onActivate,
}: StrategyCardProps) {
  const badge = RISK_BADGE[risk] ?? RISK_BADGE.balanced;

  return (
    <div
      className={`border rounded-2xl p-4 transition-colors ${
        isActive
          ? "border-gold bg-gold/5"
          : "border-border bg-card hover:border-border/60"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xl">{emoji}</span>
          <span className="text-primary font-semibold">{name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${badge.color}`}>
            {badge.label}
          </span>
          {isActive && (
            <span className="text-xs px-2 py-0.5 rounded-full border border-gold/40 bg-gold/10 text-gold font-semibold">
              ✓ ACTIVE
            </span>
          )}
        </div>
      </div>
      <p className="text-muted text-sm mb-3">{description}</p>
      <div className="flex gap-4 text-xs text-muted mb-4">
        <span>TP <span className="text-green font-medium font-mono">{tp_pct}%</span></span>
        <span>SL <span className="text-red font-medium font-mono">{sl_pct}%</span></span>
        <span>Cap <span className="text-primary font-medium font-mono">{capital_pct}%</span></span>
        <span>Freq <span className="text-primary font-medium">{freq}</span></span>
      </div>
      {isActive ? (
        <div className="text-center text-xs font-semibold text-gold border border-gold/25 rounded-button py-2 bg-gold/5">
          ✓ ACTIVE
        </div>
      ) : (
        <button
          onClick={() => onActivate(preset_key)}
          className="w-full py-2 text-sm font-semibold rounded-button bg-gold/10 text-gold border border-gold/30 hover:bg-gold/20 active:scale-95 transition-all"
        >
          Switch to {name}
        </button>
      )}
    </div>
  );
}
