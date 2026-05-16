interface PnLCardProps {
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  colorize?: boolean;
}

export function PnLCard({ label, value, prefix = "$", suffix = "", colorize = true }: PnLCardProps) {
  const isPositive = value >= 0;
  const color = colorize ? (isPositive ? "text-green" : "text-red") : "text-primary";
  const sign = colorize && value > 0 ? "+" : "";

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <p className="text-muted text-xs uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-xl font-semibold ${color}`}>
        {sign}{prefix}{Math.abs(value).toFixed(2)}{suffix}
      </p>
    </div>
  );
}
