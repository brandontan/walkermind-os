interface PnLCardProps {
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  colorize?: boolean;
  accentColor?: string; // CSS color for the 2px top accent bar
}

export function PnLCard({
  label,
  value,
  prefix = "$",
  suffix = "",
  colorize = true,
  accentColor,
}: PnLCardProps) {
  const isPositive = value >= 0;
  const color = colorize ? (isPositive ? "text-green" : "text-red") : "text-primary";
  const sign = colorize && value > 0 ? "+" : "";

  return (
    <div className="bg-card border border-border rounded-xl p-4 overflow-hidden relative">
      {accentColor && (
        <span
          className="absolute top-0 left-0 right-0"
          style={{ height: "2px", background: accentColor }}
        />
      )}
      <p className="text-muted text-xs uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-xl font-semibold font-mono ${color}`}>
        {sign}{prefix}{Math.abs(value).toFixed(2)}{suffix}
      </p>
    </div>
  );
}
