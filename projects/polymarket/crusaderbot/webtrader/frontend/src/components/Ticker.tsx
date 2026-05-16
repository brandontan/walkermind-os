type TickerItem = {
  symbol: string;
  value: string;
  delta?: string;
  dir?: "up" | "dn" | "neutral";
};

type Props = {
  items: TickerItem[];
};

export function Ticker({ items }: Props) {
  if (!items.length) return null;
  // Render the row twice so the linear scroll loops seamlessly.
  const cells = items.concat(items);
  return (
    <div
      className="relative overflow-hidden border-y border-border-1 py-[7px] mb-3 font-mono text-[10px] tracking-[0.5px]"
      style={{
        background:
          "linear-gradient(90deg, transparent 0%, #0A0F1C 10%, #0A0F1C 90%, transparent 100%)",
      }}
    >
      {/* Edge fades */}
      <span
        className="absolute inset-y-0 left-0 w-[30px] z-[2] pointer-events-none"
        style={{ background: "linear-gradient(90deg, #02050B, transparent)" }}
        aria-hidden
      />
      <span
        className="absolute inset-y-0 right-0 w-[30px] z-[2] pointer-events-none"
        style={{ background: "linear-gradient(270deg, #02050B, transparent)" }}
        aria-hidden
      />
      <div className="inline-block whitespace-nowrap animate-ticker pl-[100%]">
        {cells.map((it, i) => (
          <span key={i} className="inline-block mr-7 text-ink-3">
            <span className="text-ink-2 font-semibold tracking-[1px]">{it.symbol}</span>
            <span className="text-gold font-bold mx-1.5">{it.value}</span>
            {it.delta && (
              <span
                className={
                  it.dir === "up"
                    ? "text-grn"
                    : it.dir === "dn"
                    ? "text-red"
                    : "text-ink-3"
                }
              >
                {it.delta}
              </span>
            )}
            <span className="text-ink-4 mx-1">│</span>
          </span>
        ))}
      </div>
    </div>
  );
}
