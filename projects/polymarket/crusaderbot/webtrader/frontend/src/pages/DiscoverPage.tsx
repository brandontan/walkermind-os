import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TopBar } from "../components/TopBar";

const GAMMA_URL = "https://gamma-api.polymarket.com/markets";
const CACHE_TTL_MS = 5 * 60 * 1000;

let _cache: MarketCard[] | null = null;
let _cacheTsMs = 0;

const ALL_CATEGORIES = ["All", "Politics", "Sports", "Crypto", "Economy", "World Events"] as const;
type Category = (typeof ALL_CATEGORIES)[number];

interface GammaMarket {
  id: string;
  question: string;
  volume: number;
  liquidity: number;
  endDate: string;
  active: boolean;
  category?: string;
  outcomePrices?: string;
  outcomes?: string;
}

interface MarketCard {
  id: string;
  title: string;
  category: string;
  volume: number;
  liquidity: number;
  endDate: string;
  yesPrice: number;
  noPrice: number;
}


function fmtVolume(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

function relativeDate(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  const days = Math.ceil(diff / 86400000);
  if (days <= 0) return "closes today";
  if (days === 1) return "closes in 1d";
  if (days < 30) return `closes in ${days}d`;
  const months = Math.ceil(days / 30);
  return `closes in ${months}mo`;
}

function categoryBadge(cat: string): string {
  const map: Record<string, string> = {
    Politics: "text-blue-400 bg-blue-400/10 border-blue-400/30",
    Sports: "text-green-400 bg-green-400/10 border-green-400/30",
    Crypto: "text-purple-400 bg-purple-400/10 border-purple-400/30",
    Economy: "text-yellow-400 bg-yellow-400/10 border-yellow-400/30",
    "World Events": "text-pink-400 bg-pink-400/10 border-pink-400/30",
  };
  return map[cat] ?? "text-ink-3 bg-surface-2 border-border-2";
}

function parseGammaMarket(m: GammaMarket): MarketCard {
  let yesPrice = 0.5;
  let noPrice = 0.5;
  try {
    const prices: string[] = typeof m.outcomePrices === "string"
      ? (JSON.parse(m.outcomePrices) as string[])
      : [];
    if (prices.length >= 2) {
      yesPrice = parseFloat(prices[0]) || 0.5;
      noPrice = parseFloat(prices[1]) || 0.5;
    }
  } catch {
    // use defaults
  }
  const cat = m.category ?? "World Events";
  return {
    id: m.id,
    title: m.question,
    category: cat,
    volume: m.volume ?? 0,
    liquidity: m.liquidity ?? 0,
    endDate: m.endDate ?? new Date().toISOString(),
    yesPrice,
    noPrice,
  };
}

function MarketCardRow({ market, onDeploy }: { market: MarketCard; onDeploy: (m: MarketCard) => void }) {
  return (
    <div className="p-3 rounded-lg border border-surface-3 bg-surface-1 flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <p className="font-hud text-[11px] font-bold text-ink-1 leading-snug line-clamp-2">{market.title}</p>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className={`text-[9px] font-bold tracking-widest uppercase px-1.5 py-0.5 rounded border ${categoryBadge(market.category)}`}>
              {market.category}
            </span>
            <span className="text-[9px] font-mono text-ink-4">{relativeDate(market.endDate)}</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-1.5 text-[9px] font-mono">
        <div className="bg-surface rounded px-2 py-1">
          <span className="text-ink-4">Vol </span>
          <span className="text-ink-1 font-bold">{fmtVolume(market.volume)}</span>
        </div>
        <div className="bg-surface rounded px-2 py-1">
          <span className="text-ink-4">Liq </span>
          <span className="text-ink-1 font-bold">{fmtVolume(market.liquidity)}</span>
        </div>
        <div className="bg-surface rounded px-2 py-1">
          <span className="text-grn font-bold">YES </span>
          <span className="text-ink-1 font-bold">{(market.yesPrice * 100).toFixed(0)}¢</span>
        </div>
        <div className="bg-surface rounded px-2 py-1">
          <span className="text-red font-bold">NO </span>
          <span className="text-ink-1 font-bold">{(market.noPrice * 100).toFixed(0)}¢</span>
        </div>
      </div>

      <button
        onClick={() => onDeploy(market)}
        className="w-full py-1.5 rounded border border-gold/40 bg-gold/10 text-gold text-[10px] font-bold tracking-widest uppercase hover:bg-gold/20 transition-colors font-hud"
      >
        Deploy Bot Here
      </button>
    </div>
  );
}

export function DiscoverPage() {
  const navigate = useNavigate();
  const [markets, setMarkets] = useState<MarketCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<Category>("All");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (_cache && Date.now() - _cacheTsMs < CACHE_TTL_MS) {
        setMarkets(_cache);
        return;
      }
      const res = await fetch(
        `${GAMMA_URL}?active=true&order=volume&limit=50`,
        { headers: { Accept: "application/json" } }
      );
      if (!res.ok) throw new Error(`Gamma API ${res.status}`);
      const raw = await res.json();
      const data = Array.isArray(raw) ? raw : [];
      const parsed = (data as GammaMarket[]).map(parseGammaMarket);
      _cache = parsed;
      _cacheTsMs = Date.now();
      setMarkets(parsed);
    } catch {
      setError("Market data unavailable.");
      setMarkets([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleDeploy = useCallback((m: MarketCard) => {
    navigate(`/autotrade?market_id=${encodeURIComponent(m.id)}&market_name=${encodeURIComponent(m.title)}`);
  }, [navigate]);

  const filtered = category === "All"
    ? markets
    : markets.filter((m) => m.category === category);

  const trending = [...filtered].sort((a, b) => b.volume - a.volume).slice(0, 5);
  const highestVolume = [...filtered].sort((a, b) => b.volume - a.volume).slice(0, 5);
  const topMovers = [...filtered].sort((a, b) =>
    Math.abs(b.yesPrice - 0.5) - Math.abs(a.yesPrice - 0.5)
  ).slice(0, 5);

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">
        {/* Page header */}
        <div className="mb-3 mx-0.5">
          <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2 mb-1.5">
            <span className="w-3 h-px bg-gold" aria-hidden />
            Discover Markets
          </div>
          <p className="text-ink-3 text-xs font-mono leading-relaxed">
            Browse live Polymarket markets. Deploy your bot on any market in one tap.
          </p>
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 rounded border border-yellow-500/30 bg-yellow-500/5 text-[10px] font-mono text-yellow-400">
            {error}
          </div>
        )}

        {/* Category filter tabs */}
        <div className="flex gap-1 mb-4 overflow-x-auto pb-1 scrollbar-none">
          {ALL_CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={[
                "flex-shrink-0 px-2.5 py-1 text-[9px] font-bold tracking-widest uppercase rounded border font-hud transition-colors",
                category === cat
                  ? "text-gold border-gold/40 bg-gold/10"
                  : "text-ink-3 border-surface-3 bg-surface hover:text-ink-2",
              ].join(" ")}
            >
              {cat}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-32 rounded-lg border border-surface-3 bg-surface-1 animate-pulse" />
            ))}
          </div>
        ) : markets.length === 0 ? (
          <div className="my-6 p-4 rounded-lg border border-surface-3 bg-surface-1/50 text-center">
            <div className="text-2xl mb-2">📊</div>
            <p className="font-hud text-sm font-bold text-ink-2 mb-1">No markets available.</p>
            <p className="text-ink-3 text-xs font-mono mb-3">Market data unavailable. Check your connection.</p>
            <button
              onClick={() => void load()}
              className="font-hud text-[9px] font-bold tracking-widest text-gold uppercase px-3 py-1.5 rounded border border-gold/40 bg-gold/10 hover:bg-gold/20"
            >
              Retry
            </button>
          </div>
        ) : (
          <>
            <Section title="Trending Markets" markets={trending} onDeploy={handleDeploy} />
            <Section title="Highest Volume" markets={highestVolume} onDeploy={handleDeploy} />
            <Section title="Top Movers" markets={topMovers} onDeploy={handleDeploy} />
          </>
        )}
      </div>
    </>
  );
}

function Section({
  title,
  markets,
  onDeploy,
}: {
  title: string;
  markets: MarketCard[];
  onDeploy: (m: MarketCard) => void;
}) {
  if (markets.length === 0) return null;
  return (
    <div className="mb-5">
      <div className="font-hud text-[9px] font-bold tracking-[3px] text-ink-3 uppercase flex items-center gap-2 mb-2">
        <span className="w-2 h-px bg-gold/50" aria-hidden />
        {title}
      </div>
      <div className="space-y-2">
        {markets.map((m) => (
          <MarketCardRow key={m.id} market={m} onDeploy={onDeploy} />
        ))}
      </div>
    </div>
  );
}
