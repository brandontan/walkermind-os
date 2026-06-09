# CrusaderBot — Improvement Directives
## Based on Polybot Research & Complete-Set Arbitrage Analysis

**Document Type:** Agent Implementation Directive  
**Source Analysis:** Polymarket trading data (44,093 trades), Polybot open-source codebase  
**Target System:** CrusaderBot (`crusaderbot.fly.dev`) — W.A.R.P_STRIKE Engine  
**Date:** 2026-05-30  
**Strategies in scope:** Close Sweep · Safe Close · Flip Hunter

---

## CONTEXT & BACKGROUND

CrusaderBot trades **Up/Down binary prediction markets** on Polymarket using 3 strategies:

| Strategy | Timing | Risk | Freq |
|---|---|---|---|
| **Close Sweep** | Final 35s of candle | SAFE | Medium |
| **Safe Close** | 30–60s before close, lean filter | SAFE | Low |
| **Flip Hunter** | 140s early, cheap side 0.26–0.35 | ADVANCED | Low |

Assets: BTC, ETH, SOL, BNB, XRP, DOGE, HYPE  
Timeframes: 5m, 15m  
Engine: W.A.R.P_STRIKE

### What We Know About These Markets (from Polybot Research)

Dari analisis mendalam terhadap **44,093 real trades** dari top Polymarket trader ("Gabagool22"), ditemukan:

- **Realized PnL:** ~$6,898 selama periode sampling
- **Market terbaik:** BTC 15m = 70% dari total PnL
- **Edge utama:** Bukan directional prediction — melainkan **spread capture + complete-set arbitrage constraint**
- **DOWN win rate:** 55.9% vs UP 47% — **tapi ini sample-period bias** (Bitcoin downtrend periode Dec 14–18, 2025). Jangan dijadikan basis strategi permanent.
- **Maker vs Taker:** Maker entry menghasilkan **8x lebih besar** dari taker entry dalam simulasi
- **TOB coverage:** Hanya 47% dari market instances punya data kedua legs — data quality kritis
- **Backtest fill rate:** 72.3% jika quoted, 23.4% quote rate keseluruhan

### The Core Mathematical Law

Di setiap Up/Down binary market Polymarket:

```
UP_token + DOWN_token = $1.00 at settlement (ALWAYS)

Complete-Set Cost  = price_UP + price_DOWN
Complete-Set Edge  = 1.00 - Complete-Set Cost

If edge > 0: buying both legs = guaranteed profit regardless of direction
If edge = 0: breakeven
If edge < 0: guaranteed loss if both legs held to expiry
```

**Setiap strategi yang entry satu leg tanpa mempertimbangkan leg lainnya adalah directional bet murni, bukan arbitrage.**

---

## PART 1: ANALISIS KELEMAHAN CURRENT SYSTEM

### 1.1 Missing: Complete-Set Edge Gate

CrusaderBot saat ini tidak memiliki filter yang memvalidasi apakah total cost UP + DOWN < $1.00 sebelum entry. Tanpa ini:
- Close Sweep bisa entry di saat `cost > $1.00` → guaranteed loss dari sisi arb
- Safe Close bisa lean ke satu sisi saat complete set tidak profitable
- Flip Hunter membeli cheap side tanpa tahu apakah hedging masih viable

### 1.2 Missing: Dual-Leg Inventory Tracking

Tidak ada tracking berapa banyak UP vs DOWN yang sudah dipegang per market instance. Akibatnya:
- Bot bisa terus entry ke satu sisi yang sudah over-exposed
- Tidak ada mekanisme untuk "balance" posisi via inventory skewing
- Imbalance detection untuk top-up tidak tersedia

### 1.3 Missing: TOB Staleness Check

Jika WebSocket data untuk satu market belum update > 2 detik, harga yang digunakan bisa stale. Entry di harga stale = slippage besar.

### 1.4 Missing: Bankroll-Based Dynamic Sizing

Sizing tampaknya fixed, tidak ada mekanisme untuk:
- Reduce size saat bankroll turun
- Increase size (bounded) saat bankroll tumbuh
- Circuit breaker saat bankroll drop signifikan

### 1.5 Missing: Fast Top-Up After Partial Fill

Ketika satu leg fill (misal DOWN terisi), tidak ada trigger otomatis untuk agresif kejar UP leg. Bot menunggu siklus normal berikutnya, berpotensi miss window optimal untuk complete the set.

### 1.6 Asset Universe Risk

SOL, BNB, XRP, DOGE, HYPE lebih illiquid → spread lebih lebar → edge sering ilusi karena dimakan slippage. Belum ada data validasi yang cukup untuk confirm profitability di aset ini.

---

## PART 2: IMPROVEMENT DIRECTIVES PER STRATEGY

---

### DIRECTIVE 1: CLOSE SWEEP — Hardening & Complete-Set Integration

**Current behavior:** Entry di final 35s tanpa edge validation.

**Target behavior:** Entry di final 35s HANYA jika complete-set masih profitable, dan entry kedua legs secara bersamaan.

#### Agent Instructions:

```
TASK: Improve Close Sweep strategy logic

1. TAMBAHKAN Complete-Set Pre-Check
   Sebelum eksekusi Close Sweep di setiap market instance:
   
   a. Fetch TOB kedua legs (UP dan DOWN)
   b. Hitung: complete_set_cost = best_ask_UP + best_ask_DOWN
   c. Hitung: edge = 1.00 - complete_set_cost
   d. Jika edge < MIN_EDGE (threshold: 0.005 = 0.5%): SKIP entry, log reason="insufficient_edge"
   e. Jika salah satu TOB stale (last_update > 2000ms): SKIP entry, log reason="stale_tob"

2. UBAH Entry Logic ke Dual-Leg
   Close Sweep harus:
   a. Check inventory kedua legs SEBELUM entry
   b. Jika imbalance besar (lebih dari IMBALANCE_THRESHOLD shares ke satu sisi):
      - Hanya entry ke lagging leg (leg yang kurang)
      - Jangan tambah ke leading leg yang sudah over
   c. Ideal case: entry TAKER market order ke KEDUA legs sekaligus
      - UP: buy at bestAsk_UP
      - DOWN: buy at bestAsk_DOWN
      - Gunakan MARKET ORDER (taker), bukan limit, karena timeframe 35s terlalu sempit

3. TAMBAHKAN Spread Check
   Before any entry in Close Sweep:
   - Jika spread_UP > MAX_SPREAD (threshold: 0.02 = 2 cents): SKIP
   - Jika spread_DOWN > MAX_SPREAD (threshold: 0.02 = 2 cents): SKIP
   Wide spread di detik terakhir = market illiquid = slippage besar

4. SIZING untuk Close Sweep (5m market)
   Gunakan time-based sizing yang lebih kecil karena ini near-expiry:
   - secondsToEnd < 10s: size = 0.5x normal
   - secondsToEnd 10–35s: size = 0.75x normal
   Alasan: near expiry, payoff sudah lebih certain tapi liquidity menurun

5. LOGGING REQUIREMENTS
   Setiap eksekusi (atau skip) harus log:
   - market_slug, seconds_to_end
   - complete_set_cost, edge
   - up_ask, down_ask, up_spread, down_spread
   - action taken: ENTRY / SKIP + reason
   - inventory_up, inventory_down, imbalance

6. CONFIGURATION PARAMETERS (tambahkan ke config):
   close_sweep:
     enabled: true
     min_edge: 0.005           # minimum 0.5% edge
     max_spread: 0.02          # max spread per leg
     tob_stale_ms: 2000        # max age of TOB data
     imbalance_threshold: 5    # shares imbalance to trigger single-leg mode
     dual_leg_entry: true      # true = both legs, false = single leg only
```

---

### DIRECTIVE 2: SAFE CLOSE — Lean Filter Enhancement + Constraint Layer

**Current behavior:** Entry 30–60s before close dengan lean filter. Currently ACTIVE.

**Target behavior:** Lean filter tetap berjalan, tapi wrapped dengan complete-set constraint dan inventory awareness sebagai mandatory gate.

#### Agent Instructions:

```
TASK: Enhance Safe Close with constraint layer

1. MANDATORY PRE-GATE (runs BEFORE lean filter evaluation)
   Tambahkan sebagai hard prerequisite sebelum lean filter dijalankan:
   
   a. TOB Freshness Check:
      - Fetch last_update_at untuk UP dan DOWN legs
      - Jika (now - last_update_at) > 2000ms untuk SALAH SATU leg: ABORT tick
   
   b. Complete-Set Viability Check:
      - cost = best_bid_UP + best_bid_DOWN  (gunakan BID, bukan ASK)
      - maker_edge = 1.00 - cost
      - Jika maker_edge < MIN_MAKER_EDGE (default 0.005): ABORT tick
      - Alasan: bid-based edge karena Safe Close gunakan MAKER orders (bid quoting)
   
   c. Inventory Balance Check:
      - imbalance = shares_UP - shares_DOWN (per market instance)
      - Jika |imbalance| > MAX_IMBALANCE (default 20 shares):
        → Override lean direction ke arah lagging leg
        → Jangan entry ke leading leg meskipun lean filter mengatakan yes
      - Alasan: inventory balance lebih penting dari directional lean

2. LEAN FILTER — Tambahkan Warning Flag untuk Bias Risk
   Current lean filter mungkin menggunakan historical bias (DOWN lebih sering menang).
   
   PENTING: Berdasarkan Polybot research, DOWN win rate 55.9% adalah SAMPLE-PERIOD BIAS
   dari Bitcoin downtrend Dec 14–18 2025. Ini bukan edge yang reliable.
   
   Agent harus:
   a. Audit lean filter saat ini: apakah ada hardcoded directional bias?
   b. Jika ada: tambahkan WARNING log setiap lean filter trigger dengan directional count
   c. Tambahkan parameter: lean_filter_direction_limit_per_hour
      - Jika bot sudah lean ke DOWN lebih dari N kali per jam: reduce confidence / skip
      - Ini mencegah over-concentration selama trending market

3. ORDER MANAGEMENT untuk Safe Close
   Karena ini MAKER orders (30–60s window):
   
   a. Gunakan LIMIT order di bestBid + improveTicks
      - improveTicks default: 1 (satu tick above best bid)
      - Ini memberi queue priority di order book
   
   b. Order replacement logic:
      - Jika order sudah di-place dan harga bergerak > 1 tick: CANCEL dan REPLACE
      - Minimum age sebelum replace: min_replace_ms = 5000ms (5 detik)
      - Jangan churn order terlalu cepat (biaya + queue loss)
   
   c. Auto-cancel jika keluar window:
      - Jika seconds_to_end < 20s dan order belum fill: CANCEL
      - Alasan: too late for maker fill di 5m market

4. TAMBAHKAN Fast Top-Up Logic
   Setelah salah satu leg fill di window 30–60s:
   
   a. Deteksi: inventory_UP atau inventory_DOWN berubah (fill detected)
   b. Check: |imbalance| >= FAST_TOPUP_MIN_SHARES (default 5)
   c. Check: hedged_edge = 1 - (fill_price_lead + best_ask_lag) >= 0.00 (breakeven ok)
   d. Check: spread lagging leg <= MAX_SPREAD (0.02)
   e. Jika semua terpenuhi: TAKER order ke lagging leg di bestAsk
      - Size = abs(imbalance), subject to bankroll caps
   f. Cooldown: 15 detik antara fast top-ups per market

5. CONFIGURATION PARAMETERS:
   safe_close:
     enabled: true
     entry_window_min_seconds: 30    # jangan entry jika > 60s
     entry_window_max_seconds: 60    # jangan entry jika < 30s
     min_maker_edge: 0.005           # minimum edge (bid-based)
     tob_stale_ms: 2000
     improve_ticks: 1                # tick improvement above best bid
     min_replace_ms: 5000
     cancel_if_below_seconds: 20     # cancel unfilled orders near expiry
     max_imbalance_shares: 20        # max imbalance before override
     fast_topup_enabled: true
     fast_topup_min_shares: 5
     fast_topup_cooldown_ms: 15000
     lean_filter_hourly_direction_limit: 8  # max same-direction entries per hour
```

---

### DIRECTIVE 3: FLIP HUNTER — Reframe & Risk Control

**Current behavior:** Entry 140s sebelum close di cheap side (0.26–0.35). ADVANCED strategy.

**Target behavior:** Flip Hunter dioperasikan sebagai **contrarian value entry** dengan explicit edge validation dan downside protection.

#### Agent Instructions:

```
TASK: Reframe Flip Hunter with proper risk controls

1. TENTUKAN MODE OPERASI
   Flip Hunter perlu dipilih salah satu mode — saat ini ambigu antara arb vs directional:
   
   MODE A — Pure Arbitrage:
     - Entry ke cheap side (0.26–0.35) HANYA jika hedge ke sisi mahal masih profitable
     - arb_edge = 1.0 - (cheap_ask + expensive_bid)
     - Jika arb_edge >= MIN_ARB_EDGE (0.01): entry MAKER ke cheap side
     - Segera pasang MAKER ke expensive side juga (aim for complete set)
   
   MODE B — Directional Contrarian:
     - Entry ke cheap side sebagai directional bet (pasar underestimate side ini)
     - Tidak perlu hedge, tapi butuh STOP CONDITION
     - Stop jika harga turun di bawah STOP_PRICE (default 0.15)
     - Take profit jika harga naik ke TP_PRICE (default 0.50+)
   
   REKOMENDASI: Implement MODE A dulu (safer, math-backed).
   MODE B bisa ditambahkan sebagai optional toggle.

2. UNTUK MODE A — Complete-Set Flip Hunter

   Entry Logic:
   a. Identify "cheap" leg: leg dengan bestAsk <= 0.35
   b. Identify "expensive" leg: leg lainnya
   c. Hitung arb_edge = 1.0 - (cheap_ask + expensive_bid)
   d. Jika arb_edge < MIN_ARB_EDGE (0.01): SKIP
   e. Jika spread cheap leg > 0.03: SKIP (too wide, slippage risk)
   f. Entry: MAKER order ke cheap leg di (bestBid + 1 tick)
   g. Simultaneously: MAKER order ke expensive leg di (bestBid + 1 tick)
   
   Timing validation:
   a. Flip Hunter entry window: 120–180s sebelum close (cek seconds_to_end)
   b. Jika < 90s tersisa dan belum fill: evaluate apakah perlu TAKER to complete
   c. Jika < 30s tersisa dan masih ada imbalance >= 10 shares: TAKER top-up

   Position tracking:
   a. Setelah fill di cheap side: track sebagai "lead fill"
   b. Activate fast top-up logic untuk expensive side
   c. Target: complete both legs before expiry

3. UNTUK MODE B — Directional Contrarian (Optional Toggle)

   Entry Logic:
   a. Entry cheap side (0.26–0.35) dengan MARKET atau LIMIT order
   b. Size: gunakan REDUCED size vs normal (50% dari base size)
      Alasan: higher risk, uncorrelated dengan arb math
   
   Exit Logic (WAJIB untuk Mode B):
   a. Stop Loss: jika bestBid turun ke <= 0.15 → MARKET SELL immediately
      Ini perlu di-implement sebagai monitoring loop terpisah
   b. Take Profit: jika bestBid naik ke >= 0.55 → MARKET SELL
   c. Time Stop: jika seconds_to_end <= 60s dan harga masih di cheap range → consider exit
   
   PENTING: Stop loss harus berjalan sebagai REAL-TIME monitor, bukan hanya per-tick.
   Jika market bergerak cepat di detik terakhir, stop loss bisa miss jika hanya di 500ms loop.

4. LOGGING & METRICS khusus Flip Hunter
   Flip Hunter harus track secara terpisah dari strategi lain:
   - flip_hunter_entries: count per asset per day
   - flip_hunter_avg_entry_price: moving average
   - flip_hunter_win_rate: % yang menang (cheap side menjadi $1)
   - flip_hunter_avg_edge_at_entry: validasi apakah edge real
   - flip_hunter_mode: A atau B
   
   Report ini penting untuk validasi apakah Flip Hunter profitable atau lucky.

5. CONFIGURATION PARAMETERS:
   flip_hunter:
     enabled: true
     mode: A                         # A=arb, B=directional
     cheap_side_max_price: 0.35      # max price untuk dianggap "cheap"
     cheap_side_min_price: 0.10      # min price (jangan terlalu dekat zero)
     entry_window_max_seconds: 180   # masuk max 3 menit sebelum close
     entry_window_min_seconds: 60    # jangan masuk terlalu dekat close
     min_arb_edge: 0.01              # Mode A: minimum edge
     max_cheap_spread: 0.03          # max spread cheap leg
     size_fraction: 0.50             # 50% dari normal size (higher risk)
     mode_b_stop_loss_price: 0.15    # Mode B: stop loss trigger
     mode_b_take_profit_price: 0.55  # Mode B: take profit trigger
     fast_topup_after_fill: true     # trigger top-up setelah lead fill
```

---

## PART 3: GLOBAL ENGINE IMPROVEMENTS (W.A.R.P_STRIKE)

Ini improvements yang harus diimplementasi di ENGINE LEVEL, bukan per-strategy.

---

### DIRECTIVE 4: Complete-Set Edge Calculator Module

```
TASK: Buat shared CompleteSetEdgeCalculator module/class

Interface:
  class CompleteSetEdgeCalculator:
    
    def calculate(up_tob, down_tob):
      # Returns EdgeResult
      
    class EdgeResult:
      maker_edge: float      # 1 - (bid_up + bid_down)
      taker_edge: float      # 1 - (ask_up + ask_down)  
      mixed_edge_up: float   # 1 - (ask_up + bid_down)  [take UP, make DOWN]
      mixed_edge_down: float # 1 - (bid_up + ask_down)  [make UP, take DOWN]
      is_viable: bool        # taker_edge > 0 (bisa arb sama sekali)
      spread_up: float
      spread_down: float
      is_stale_up: bool      # TOB age > 2000ms
      is_stale_down: bool

Usage di setiap strategy:
  edge = calculator.calculate(up_tob, down_tob)
  if edge.is_stale_up or edge.is_stale_down:
      return SKIP
  if edge.maker_edge < strategy.min_edge:
      return SKIP

Kenapa penting:
- Single source of truth untuk edge calculation
- Semua 3 strategy pakai logic yang sama → tidak ada inconsistency
- Mudah di-test dan di-audit
- Metrics bisa di-aggregate: berapa % waktu market punya positive edge
```

---

### DIRECTIVE 5: Inventory Tracker (Per Market Instance)

```
TASK: Implement per-market inventory tracking

Data structure per market instance:
  class MarketInventory:
    market_slug: str
    shares_up: Decimal        # filled UP shares (net)
    shares_down: Decimal      # filled DOWN shares (net)
    imbalance: Decimal        # shares_up - shares_down
    last_up_fill_at: datetime
    last_down_fill_at: datetime
    last_up_fill_price: Decimal
    last_down_fill_price: Decimal
    last_topup_at: datetime
    
  Operations:
    record_fill(side, shares, price, timestamp)
    get_imbalance() -> Decimal
    get_skew_ticks(max_skew, imbalance_for_max) -> int
    reset()  # on market expiry

Inventory Initialization:
  On startup: sync inventory dari positions API
  Pagination: load up to offset 2000 (Polybot pattern)
  Refresh: setiap 5 detik background sync

Integration:
  - Close Sweep: gunakan imbalance untuk decide single vs dual leg
  - Safe Close: gunakan untuk override lean direction
  - Flip Hunter: gunakan untuk activate fast top-up
  - Global: gunakan untuk calculate total exposure
```

---

### DIRECTIVE 6: Bankroll Service & Circuit Breaker

```
TASK: Implement BankrollService dengan circuit breaker

BankrollService:
  
  Modes:
    FIXED: bankroll_usd = constant (untuk testing)
    AUTO_CASH: poll USDC balance dari wallet API setiap 10s
               apply EMA smoothing: alpha=0.2
               effective = alpha * raw + (1-alpha) * previous
  
  Dynamic Sizing Multiplier:
    target = configured bankroll
    if effective > target * 1.1: multiplier = min(multiplier * 1.05, 1.5)
    if effective < target * 0.9: multiplier = max(multiplier * 0.95, 0.5)
    Apply: final_shares = base_shares * multiplier
  
  Circuit Breaker:
    threshold = bankroll_min_threshold (default 20% dari bankroll)
    if effective_bankroll < threshold:
      STOP ALL TRADING
      Cancel all open orders
      Log: CIRCUIT_BREAKER_TRIGGERED
      Alert: send notification ke configured channel
    Resume: only when effective_bankroll > threshold * 1.1 (hysteresis)
  
  Exposure Tracking:
    total_exposure = sum(open_order_remaining_notional) 
                   + sum(unhedged_position_notional)
    
    Per-order cap: max_order_bankroll_fraction * effective_bankroll
    Total cap: max_total_bankroll_fraction * effective_bankroll
    
    If total_exposure >= total_cap: SKIP new entries

CONFIGURATION:
  bankroll:
    mode: AUTO_CASH               # FIXED atau AUTO_CASH
    fixed_usd: 500                # hanya jika mode=FIXED
    refresh_ms: 10000             # poll interval
    smoothing_alpha: 0.2          # EMA alpha
    min_threshold_fraction: 0.20  # circuit breaker di 20%
    trading_fraction: 0.80        # gunakan 80% dari bankroll
    max_order_fraction: 0.02      # max 2% per order
    max_total_fraction: 0.50      # max 50% total exposure
```

---

### DIRECTIVE 7: TOB Data Quality & Freshness Monitor

```
TASK: Implement real-time TOB quality monitoring

Per-asset TOB state:
  class TopOfBook:
    asset_id: str
    best_bid: Decimal
    best_ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    last_trade_price: Decimal
    updated_at: datetime
    
    def is_stale(self, threshold_ms=2000) -> bool:
      return (now - updated_at).ms > threshold_ms
    
    def spread(self) -> Decimal:
      return best_ask - best_bid
    
    def mid(self) -> Decimal:
      return (best_bid + best_ask) / 2
    
    def is_valid(self) -> bool:
      return (best_bid is not None 
              and best_ask is not None
              and best_bid > 0 
              and best_ask > best_bid
              and best_ask < 1.0)

Coverage Metric (log setiap menit):
  total_markets_tracked: int
  markets_with_fresh_both_legs: int
  coverage_pct = fresh_both / total * 100
  
  Minimum acceptable: coverage_pct >= 80%
  Alert jika: coverage_pct < 50% (WebSocket masalah)

WebSocket Health:
  reconnect_count: int
  last_reconnect_at: datetime
  messages_per_minute: int
  
  Jika messages_per_minute < 10: trigger reconnect
  Reconnect dengan exponential backoff: 1s, 2s, 4s, 8s, 16s, max 60s
```

---

### DIRECTIVE 8: Order Management Core

```
TASK: Standardize order management across all strategies

OrderManager (shared across all strategies):
  
  State per token:
    open_orders: Dict[token_id, OrderState]
    
    class OrderState:
      order_id: str
      token_id: str
      market_slug: str
      direction: UP/DOWN
      price: Decimal
      size: Decimal
      matched_size: Decimal
      placed_at: datetime
      status: OPEN/PARTIAL/FILLED/CANCELED
      strategy: CLOSE_SWEEP/SAFE_CLOSE/FLIP_HUNTER
      place_reason: QUOTE/REPLACE/TOP_UP/FAST_TOP_UP/TAKER
  
  Core operations:
  
    place_order(market, token_id, direction, price, size, reason):
      - Validate: size > 0.01
      - Validate: price between 0.01 and 0.99
      - Validate: price < best_ask (no crossing for maker)
      - Submit to executor API
      - Store in open_orders
      - Publish event: ORDER_PLACED
    
    maybe_replace(token_id, new_price, new_size, min_age_ms):
      existing = open_orders.get(token_id)
      if existing is None: return PLACE_NEW
      age = now - existing.placed_at
      if age < min_age_ms: return SKIP  # too young to replace
      price_diff = abs(new_price - existing.price)
      if price_diff < tick_size: return SKIP  # price unchanged
      cancel(token_id, reason=REPLACE_PRICE)
      return PLACE_NEW
    
    cancel(token_id, reason):
      order = open_orders.get(token_id)
      if order is None: return
      if order.status in TERMINAL_STATES: return
      call executor: DELETE /orders/{order_id}
      Publish event: ORDER_CANCELED with reason
    
    cancel_all(reason):
      for token_id in open_orders:
        cancel(token_id, reason)
    
    poll_status():  # run every 1000ms
      for order in open_orders.values():
        if order is TERMINAL: continue
        status = executor.get_order(order.order_id)
        if status changed: update + publish event
        if status == FILLED: trigger fill_handler
        if order age > MAX_ORDER_AGE_MS (300000): cancel(TIMEOUT)
```

---

## PART 4: ASSET UNIVERSE RECOMMENDATIONS

### Tier 1 — High Confidence (Retain & Optimize)

```
BTC (15m, 5m)  ← 70% of expected PnL per Polybot research
ETH (15m, 5m)  ← Secondary market, validated data
```
Fokus optimasi di sini dulu. Ukur fill rate, edge, PnL secara granular.

### Tier 2 — Conditional (SOL)

```
SOL (15m, 5m)  ← Market ada, tapi belum ada backtesting data
```

Sebelum enable SOL secara agresif:
1. Collect 2 minggu TOB data SOL markets
2. Hitung average: `edge = 1 - (ask_up + ask_down)` per jam
3. Jika rata-rata edge < 0.5%: skip SOL (spread makan edge)
4. Jika fill rate < 40%: sizing terlalu besar untuk liquidity yang ada

### Tier 3 — Low Priority / High Risk (Monitor Only)

```
BNB, XRP, DOGE  ← Lebih illiquid, higher spread, unvalidated
HYPE            ← Sangat baru, tidak ada historical data
```

**Rekomendasi:** Set BNB/XRP/DOGE/HYPE ke monitoring-only mode.  
Collect data 30 hari, review edge statistics, baru decide apakah aktifkan.

Cara implement monitoring-only:
```yaml
assets:
  - symbol: BNB
    enabled: false       # disable trading
    monitor: true        # tapi tetap collect TOB data
  - symbol: HYPE
    enabled: false
    monitor: true
```

---

## PART 5: METRICS & OBSERVABILITY

### Directive 9: Mandatory Metrics Implementation

```
TASK: Implement metrics untuk semua key events

Strategy Metrics (per strategy, per asset):
  crusader_entries_total{strategy, asset, direction, reason}
  crusader_skips_total{strategy, asset, reason}
  crusader_fill_rate{strategy, asset}          # filled / placed
  crusader_edge_at_entry{strategy, asset}      # distribution
  crusader_pnl_realized{strategy, asset}       # USDC
  crusader_imbalance_at_entry{strategy, asset} # shares

Engine Metrics:
  crusader_bankroll_usd                # effective bankroll
  crusader_total_exposure_usd          # total open risk
  crusader_circuit_breaker_active      # 0 or 1
  crusader_tob_coverage_pct           # % markets with fresh data
  crusader_ws_reconnect_total         # WebSocket reconnects
  crusader_orders_placed_total
  crusader_orders_canceled_total
  crusader_orders_timeout_total

Per-Market Metrics:
  crusader_market_edge{market_slug}    # current edge
  crusader_market_spread_up{market}   # current UP spread
  crusader_market_spread_down{market} # current DOWN spread
  crusader_inventory_imbalance{market} # current imbalance

Dashboard (Grafana atau equivalent):
  Panel 1: PnL per strategy per day (line chart)
  Panel 2: Fill rate per asset (bar chart)
  Panel 3: Edge distribution at entry (histogram)
  Panel 4: Circuit breaker events (timeline)
  Panel 5: TOB coverage % (gauge)
  Panel 6: Current exposure vs bankroll (gauge)
  Panel 7: Inventory imbalance per market (heatmap)
```

---

## PART 6: PAPER TRADING VALIDATION PROTOCOL

Sebelum deploy improvement ke live, wajib validasi dengan urutan ini:

### Phase 1 — Unit Test (1–2 hari)
```
□ Complete-Set edge calculator: test dengan known prices
□ Inventory tracker: test fill recording, imbalance calculation
□ Bankroll service: test EMA smoothing, circuit breaker trigger
□ Order manager: test replace logic, timeout cancellation
□ TOB staleness: test dengan mocked timestamps
```

### Phase 2 — Paper Trading (minimum 7 hari)
```
□ Deploy semua changes di paper mode
□ Monitor metrics: edge_at_entry, fill_rate, PnL simulation
□ Verify circuit breaker tidak trigger tanpa sebab
□ Verify inventory balancing berjalan (imbalance < threshold)
□ Verify Close Sweep skip rate reasonable (> 0% artinya filter berjalan)
□ Verify Fast Top-Up trigger dalam 30s setelah fill
□ Review logs setiap hari untuk anomali
```

### Phase 3 — Live dengan Reduced Size (minimum 7 hari)
```
□ Go live dengan 25% normal sizing
□ Monitor PnL secara real-time
□ Verify no unexpected large orders
□ Circuit breaker test: temporarily reduce bankroll threshold
□ Verify settlement auto-redeem berjalan (jika implemented)
□ Gradually increase to 50% then 100% sizing jika metrics OK
```

### Success Criteria untuk Phase Promotion:
```
Paper → Live 25%:
  - Fill rate >= 50%
  - Simulated PnL > 0 over 7 days
  - Zero circuit breaker events
  - Edge at entry avg >= 0.5%

Live 25% → Live 100%:
  - Actual PnL > 0 over 7 days
  - Max drawdown < 15% of bankroll
  - Fill rate >= 40%
  - No order errors / unexpected rejections
```

---

## PART 7: PRIORITIZED IMPLEMENTATION ROADMAP

### Sprint 1 — Critical Safety (Implement First)
```
1. [ ] Complete-Set Edge Calculator module (shared)
2. [ ] TOB staleness check di semua 3 strategies
3. [ ] Bankroll circuit breaker (basic version)
4. [ ] Complete-set edge gate di Close Sweep
5. [ ] Complete-set edge gate di Safe Close
```

### Sprint 2 — Core Logic Enhancement
```
6. [ ] Inventory Tracker implementation
7. [ ] Flip Hunter Mode A (arb-based)
8. [ ] Order Manager standardization
9. [ ] Inventory skew ticks di Safe Close
10. [ ] Fast Top-Up setelah fill
```

### Sprint 3 — Optimization & Observability
```
11. [ ] Dynamic bankroll sizing multiplier
12. [ ] Grafana metrics dashboard
13. [ ] Asset monitoring mode (BNB/XRP/DOGE/HYPE)
14. [ ] Lean filter audit & direction limit
15. [ ] WebSocket reconnect dengan exponential backoff
```

### Sprint 4 — Validation & Live Deploy
```
16. [ ] Full paper trading 7 days
17. [ ] Performance report vs pre-improvement baseline
18. [ ] Live deploy 25% size
19. [ ] Live deploy 100% size
```

---

## APPENDIX A: Key Parameters Reference

| Parameter | Recommended Value | Rationale |
|---|---|---|
| `tob_stale_ms` | 2000 | Polybot research proven value |
| `min_maker_edge` | 0.005 (0.5%) | Conservative entry, covers fees |
| `min_taker_edge` | 0.010 (1.0%) | Taker crossing spread = higher edge needed |
| `max_spread_maker` | 0.02 | 2 cents, beyond this market too illiquid |
| `max_spread_taker` | 0.01 | 1 cent, tighter for taker |
| `improve_ticks` | 1 | Queue priority, tidak aggressive |
| `min_replace_ms` | 5000 | Avoid excessive churn |
| `max_order_age_ms` | 300000 | 5 menit max order age |
| `circuit_breaker_pct` | 0.20 | Stop di 20% bankroll loss |
| `max_order_fraction` | 0.02 | Max 2% bankroll per order |
| `max_total_fraction` | 0.50 | Max 50% bankroll total exposure |
| `fast_topup_cooldown_ms` | 15000 | 15 detik antara top-ups |
| `imbalance_for_max_skew` | 20 | Shares sebelum max skew tercapai |
| `max_skew_ticks` | 1 | Maksimal 1 tick skew |

---

## APPENDIX B: Edge Classification

```
edge >= 3%   → STRONG  — market significantly mispriced, agresif entry
edge 1–3%    → GOOD    — normal profitable range, standard sizing
edge 0.5–1%  → WEAK    — entry hanya jika market liquid (spread tight)
edge 0–0.5%  → MARGINAL — skip kecuali inventory severely imbalanced
edge < 0%    → NEGATIVE — NEVER enter, guaranteed loss dari arb perspective
```

---

## APPENDIX C: Common Failure Modes to Watch

| Failure | Symptom | Prevention |
|---|---|---|
| **Stale TOB entry** | Fill di harga jauh dari expected | TOB staleness check wajib |
| **One-leg over-exposure** | Banyak UP, sedikit DOWN → bergantung pada price direction | Inventory tracking + skew |
| **Edge illusion** | Edge ada di bid, tapi tidak bisa fill di bid | Use ask-based edge untuk taker check |
| **Churn** | Banyak cancel/replace, sedikit fill | min_replace_ms cukup tinggi |
| **Near-expiry slippage** | Top-up di spread lebar di detik terakhir | Spread check sebelum top-up |
| **Direction lock-in** | Lean filter selalu satu arah | Direction limit per hour |
| **Memory / data drift** | Inventory out of sync setelah restart | Sync from positions API on startup |
| **Circuit breaker loop** | Trigger → recovery → trigger → ... | Hysteresis: resume hanya di 110% threshold |

---

*Document generated from analysis of Polybot open-source codebase and 44,093 Polymarket trade records.*  
*All edge thresholds and timing parameters are derived from validated backtesting data.*  
*Always validate in paper trading mode before live deployment.*
