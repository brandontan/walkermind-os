interface StrategyCardProps {
  name: string;
  preset_key: string;
  description: string;
  risk: "safe" | "balanced" | "aggressive";
  tp_pct: number;
  sl_pct: number;
  capital_pct: number;
  isActive: boolean;
  onActivate: (key: string) => void;
}

const RISK_BADGE: Record<string, { label: string; color: string }> = {
  safe:       { label: "SAFE",       color: "text-green bg-green/10 border-green/30" },
  balanced:   { label: "BALANCED",   color: "text-yellow bg-yellow/10 border-yellow/30" },
  aggressive: { label: "AGGRESSIVE", color: "text-red bg-red/10 border-red/30" },
};

export function StrategyCard({
  name, preset_key, description, risk, tp_pct, sl_pct, capital_pct, isActive, onActivate,
}: StrategyCardProps) {
  const badge = RISK_BADGE[risk] ?? RISK_BADGE.balanced;

  return (
    <div className={`bg-card border rounded-xl p-4 ${isActive ? "border-amber" : "border-border"}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-primary font-semibold">{name}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${badge.color}`}>
          {badge.label}
        </span>
      </div>
      <p className="text-muted text-sm mb-3">{description}</p>
      <div className="flex gap-4 text-xs text-muted mb-4">
        <span>TP <span className="text-green font-medium">{tp_pct}%</span></span>
        <span>SL <span className="text-red font-medium">{sl_pct}%</span></span>
        <span>Capital <span className="text-primary font-medium">{capital_pct}%</span></span>
      </div>
      {isActive ? (
        <div className="text-center text-xs font-semibold text-amber border border-amber/30 rounded-lg py-1.5">
          ACTIVE
        </div>
      ) : (
        <button
          onClick={() => onActivate(preset_key)}
          className="w-full py-2 text-sm font-semibold rounded-lg bg-amber/10 text-amber border border-amber/30 hover:bg-amber/20 transition-colors"
        >
          Switch to This
        </button>
      )}
    </div>
  );
}
