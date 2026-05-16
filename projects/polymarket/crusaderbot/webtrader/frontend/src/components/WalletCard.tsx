type Props = {
  label: string;
  balance: string;
  unit?: string;
  mode?: string;
};

export function WalletCard({ label, balance, unit = "USDC", mode }: Props) {
  return (
    <div
      className="relative overflow-hidden mb-3 p-[18px_16px] border border-border-2 clip-card-lg"
      style={{
        background: "linear-gradient(135deg, #0E1830 0%, #0A1322 100%)",
      }}
    >
      <span
        className="absolute pointer-events-none"
        style={{
          top: "-50px",
          right: "-50px",
          width: "150px",
          height: "150px",
          background:
            "radial-gradient(ellipse, rgba(245,200,66,0.08) 0%, transparent 65%)",
        }}
        aria-hidden
      />
      <div className="font-mono text-[9px] font-bold tracking-[2.5px] text-ink-3 uppercase mb-1.5">
        <span className="text-gold">◢ </span>{label}
      </div>
      <div
        className="font-display leading-none mb-1"
        style={{
          fontSize: "48px",
          background:
            "linear-gradient(180deg, #FFFFFF 0%, #FFE066 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}
      >
        {balance}
        <span
          className="ml-2"
          style={{
            fontSize: "14px",
            letterSpacing: "2px",
            WebkitTextFillColor: "var(--ink-3,#455370)",
            background: "none",
            color: "var(--ink-3,#455370)",
          }}
        >
          {unit}
        </span>
      </div>
      {mode && (
        <div className="font-mono text-[10px] text-ink-2 tracking-[1px]">{mode}</div>
      )}
    </div>
  );
}
