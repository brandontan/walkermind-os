import { useEffect, useMemo, useState } from "react";
import type {
  AdminRecentAudit,
  AdminRecentTrade,
  AdminUserDetail,
  AdminUserPatch,
} from "../lib/api";
import { makeApi } from "../lib/api";
import { useAuth } from "../lib/auth";

interface Props {
  userId: string;
  onClose: () => void;
  onSaved?: (next: AdminUserDetail) => void;
}

const PRESETS = ["close_sweep", "safe_close", "flip_hunter"] as const;
const RISK_PROFILES = ["conservative", "balanced", "aggressive", "custom"] as const;
const MAX_PER_TRADE_MODES = ["auto", "fixed", "pct"] as const;
const TIMEFRAMES = ["5m", "15m"] as const;
const CRYPTO_ASSETS = ["BTC", "ETH", "SOL"] as const;
const CRYPTO_SHORT_PRESETS = new Set<string>(["close_sweep", "safe_close", "flip_hunter"]);

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function shortAddr(addr: string | null | undefined): string {
  if (!addr) return "—";
  if (addr.length <= 14) return addr;
  return `${addr.slice(0, 8)}…${addr.slice(-6)}`;
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const diff = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function AdminUserDrawer({ userId, onClose, onSaved }: Props) {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);

  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  // Editable draft — mirrors AdminUserPatch but with all fields tracked as
  // local strings so the user can clear / edit without us mid-eating an empty
  // input. Empty string === "leave unchanged" (NOT "clear to null").
  const [draft, setDraft] = useState<{
    active_preset: string;
    risk_profile: string;
    capital_alloc_pct: string;
    tp_pct: string;
    sl_pct: string;
    max_per_trade_mode: string;
    max_per_trade_usdc: string;
    max_per_trade_pct: string;
    selected_timeframe: string;
    selected_assets: string[] | null;  // null = unchanged; [] = clear; [...] = explicit set
  }>({
    active_preset: "",
    risk_profile: "",
    capital_alloc_pct: "",
    tp_pct: "",
    sl_pct: "",
    max_per_trade_mode: "",
    max_per_trade_usdc: "",
    max_per_trade_pct: "",
    selected_timeframe: "",
    selected_assets: null,
  });

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setDetail(null);
    api.getAdminUserDetail(userId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        setDraft({
          active_preset: d.active_preset ?? "",
          risk_profile: d.risk_profile,
          capital_alloc_pct: String(d.capital_alloc_pct * 100),
          tp_pct: d.tp_pct == null ? "" : String(d.tp_pct * 100),
          sl_pct: d.sl_pct == null ? "" : String(d.sl_pct * 100),
          max_per_trade_mode: d.max_per_trade_mode,
          max_per_trade_usdc: d.max_per_trade_usdc == null ? "" : String(d.max_per_trade_usdc),
          max_per_trade_pct: d.max_per_trade_pct == null ? "" : String(d.max_per_trade_pct * 100),
          selected_timeframe: d.selected_timeframe ?? "",
          selected_assets: null,
        });
      })
      .catch((e) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg.replace(/^\d+:\s*/, ""));
      });
    return () => { cancelled = true; };
  }, [api, userId]);

  function buildPatch(): AdminUserPatch | null {
    if (!detail) return null;
    const patch: AdminUserPatch = {};
    if (draft.active_preset && draft.active_preset !== (detail.active_preset ?? "")) {
      patch.active_preset = draft.active_preset;
    }
    if (draft.risk_profile && draft.risk_profile !== detail.risk_profile) {
      patch.risk_profile = draft.risk_profile;
    }
    const cap = Number(draft.capital_alloc_pct) / 100;
    if (draft.capital_alloc_pct !== "" && Number.isFinite(cap) && cap !== detail.capital_alloc_pct) {
      patch.capital_alloc_pct = cap;
    }
    const tp = Number(draft.tp_pct) / 100;
    const tpInput = draft.tp_pct.trim();
    if (tpInput !== "" && Number.isFinite(tp) && tp !== detail.tp_pct) {
      patch.tp_pct = tp;
    }
    const sl = Number(draft.sl_pct) / 100;
    const slInput = draft.sl_pct.trim();
    if (slInput !== "" && Number.isFinite(sl) && sl !== detail.sl_pct) {
      patch.sl_pct = sl;
    }
    if (draft.max_per_trade_mode && draft.max_per_trade_mode !== detail.max_per_trade_mode) {
      patch.max_per_trade_mode = draft.max_per_trade_mode;
    }
    const mptu = Number(draft.max_per_trade_usdc);
    if (draft.max_per_trade_usdc !== "" && Number.isFinite(mptu) && mptu !== detail.max_per_trade_usdc) {
      patch.max_per_trade_usdc = mptu;
    }
    const mptp = Number(draft.max_per_trade_pct) / 100;
    if (draft.max_per_trade_pct !== "" && Number.isFinite(mptp) && mptp !== detail.max_per_trade_pct) {
      patch.max_per_trade_pct = mptp;
    }
    if (draft.selected_timeframe && draft.selected_timeframe !== (detail.selected_timeframe ?? "")) {
      patch.selected_timeframe = draft.selected_timeframe;
    }
    if (draft.selected_assets !== null) {
      // Only send if the operator actively toggled an asset. Empty array
      // clears the column (NULL on the backend); a non-empty array sets it.
      const current = detail.selected_assets ?? [];
      const next = draft.selected_assets;
      const changed =
        next.length !== current.length ||
        next.some((a) => !current.includes(a)) ||
        current.some((a) => !next.includes(a));
      if (changed) {
        patch.selected_assets = next;
      }
    }
    return patch;
  }

  async function handleSave() {
    if (!detail) return;
    const patch = buildPatch();
    if (!patch || Object.keys(patch).length === 0) {
      setSavedNote("No changes to save.");
      return;
    }
    setSaving(true);
    setError(null);
    setSavedNote(null);
    try {
      const next = await api.updateAdminUser(userId, patch);
      setDetail(next);
      setDraft((d) => ({ ...d, selected_assets: null }));
      setSavedNote("Saved.");
      onSaved?.(next);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg.replace(/^\d+:\s*/, ""));
    } finally {
      setSaving(false);
    }
  }

  async function togglePaused(nextPaused: boolean) {
    if (!detail) return;
    setSaving(true);
    setError(null);
    setSavedNote(null);
    try {
      const next = await api.updateAdminUser(userId, { paused: nextPaused });
      setDetail(next);
      setSavedNote(nextPaused ? "User paused." : "User resumed.");
      onSaved?.(next);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg.replace(/^\d+:\s*/, ""));
    } finally {
      setSaving(false);
    }
  }

  function toggleAsset(asset: string) {
    setDraft((d) => {
      const base = d.selected_assets ?? (detail?.selected_assets ?? []).slice();
      const has = base.includes(asset);
      const next = has ? base.filter((a) => a !== asset) : [...base, asset];
      return { ...d, selected_assets: next };
    });
  }

  const label = detail
    ? (detail.username ? `@${detail.username}` : (detail.email ?? detail.user_id.slice(0, 8)))
    : userId.slice(0, 8);

  const activePreset = draft.active_preset || (detail?.active_preset ?? "");
  const showCryptoShortFields = CRYPTO_SHORT_PRESETS.has(activePreset);
  const effectiveAssets = draft.selected_assets ?? detail?.selected_assets ?? [];

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center px-2"
      style={{ background: "rgba(0,0,0,0.78)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label="User detail"
    >
      {/* 3-region layout (mobile-friendly):
            - sticky header: always-visible close ×
            - scrollable body: form fields
            - sticky footer: Cancel/Save above the BottomNav (z-100)
          z-[200] beats BottomNav so the modal is never obstructed. */}
      <div
        className="w-full max-w-lg bg-surface border border-border-1 clip-card flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* === sticky header === */}
        <div className="flex items-start justify-between p-4 pb-3 border-b border-surface-3 flex-shrink-0">
          <div>
            <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-gold mb-1">User Detail</p>
            <p className="font-mono text-[13px] text-ink-1">
              {label}
              {detail?.role === "admin" && <span className="ml-2 text-gold text-[8px]">ADMIN</span>}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="font-mono text-[16px] text-ink-3 hover:text-ink-1 px-3 py-1 -mr-1 -mt-1"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* === scrollable body === */}
        <div className="flex-1 overflow-y-auto p-4 pt-3">
        {error && <p className="text-red text-[11px] font-mono mb-2">{error}</p>}
        {!detail && !error && (
          <p className="text-ink-3 text-[11px] font-mono">Loading user detail…</p>
        )}

        {detail && (
          <>
            {/* Read-only runtime snapshot */}
            <div className="grid grid-cols-2 gap-2 mb-3">
              <Stat label="Mode" value={detail.trading_mode.toUpperCase()} />
              <Stat label="Auto" value={detail.paused ? "PAUSED" : detail.auto_trade_on ? "ON" : "OFF"} />
              <Stat label="Balance" value={fmtUsd(detail.balance_usdc)} />
              <Stat label="Open positions" value={String(detail.open_positions)} />
            </div>

            {/* Identity block */}
            <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-gold mb-2">Identity</p>
            <div className="grid grid-cols-2 gap-2 mb-3">
              <Stat label="Email" value={detail.email ?? "—"} />
              <Stat label="Telegram" value={detail.telegram_user_id != null ? String(detail.telegram_user_id) : "—"} />
              <div className="col-span-2 bg-surface-2 border border-surface-3 rounded-sm px-2.5 py-1.5">
                <p className="font-hud text-[8px] tracking-[1px] uppercase text-ink-4">Wallet</p>
                <p
                  className="font-mono text-[11px] text-ink-1 mt-0.5 truncate"
                  title={detail.wallet_address ?? ""}
                >
                  {shortAddr(detail.wallet_address)}
                </p>
              </div>
            </div>

            {/* Per-user pause toggle */}
            <div className="flex items-center justify-between gap-2 bg-surface-2 border border-surface-3 rounded-sm px-2.5 py-2 mb-4">
              <div className="min-w-0">
                <p className="font-hud text-[8px] tracking-[1px] uppercase text-ink-4">User Paused</p>
                <p className="font-mono text-[11px] text-ink-1 mt-0.5">
                  {detail.paused
                    ? "Risk gate is blocking new trades for this user."
                    : "User is active. Risk gate accepts trades."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void togglePaused(!detail.paused)}
                disabled={saving}
                className={`flex-shrink-0 font-mono text-[10px] tracking-[1px] uppercase px-3 py-1.5 rounded-sm disabled:opacity-50 ${
                  detail.paused
                    ? "bg-green/80 hover:bg-green text-ink-1"
                    : "bg-red/80 hover:bg-red text-ink-1"
                }`}
              >
                {detail.paused ? "Resume" : "Pause"}
              </button>
            </div>

            {/* Strategy + risk edit */}
            <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-gold mb-2">Edit Bot Settings</p>
            <div className="space-y-2.5">
              <FieldSelect
                label="Active preset"
                value={draft.active_preset}
                options={PRESETS}
                placeholder="(unchanged)"
                onChange={(v) => setDraft({ ...draft, active_preset: v })}
              />
              <FieldSelect
                label="Risk profile"
                value={draft.risk_profile}
                options={RISK_PROFILES}
                placeholder={detail.risk_profile}
                onChange={(v) => setDraft({ ...draft, risk_profile: v })}
              />
              <FieldNumber
                label={`Capital alloc % (1–80, now ${fmtPct(detail.capital_alloc_pct)})`}
                value={draft.capital_alloc_pct}
                step="1"
                min="1"
                max="80"
                onChange={(v) => setDraft({ ...draft, capital_alloc_pct: v })}
              />
              <FieldNumber
                label={`TP % (0.5–100, now ${fmtPct(detail.tp_pct)})`}
                value={draft.tp_pct}
                step="0.5"
                min="0.5"
                max="100"
                onChange={(v) => setDraft({ ...draft, tp_pct: v })}
              />
              <FieldNumber
                label={`SL % (0.5–100, now ${fmtPct(detail.sl_pct)})`}
                value={draft.sl_pct}
                step="0.5"
                min="0.5"
                max="100"
                onChange={(v) => setDraft({ ...draft, sl_pct: v })}
              />
              <FieldSelect
                label="Max-per-trade mode"
                value={draft.max_per_trade_mode}
                options={MAX_PER_TRADE_MODES}
                placeholder={detail.max_per_trade_mode}
                onChange={(v) => setDraft({ ...draft, max_per_trade_mode: v })}
              />
              <FieldNumber
                label={`Max per trade $ (1–500, now ${fmtUsd(detail.max_per_trade_usdc)})`}
                value={draft.max_per_trade_usdc}
                step="1"
                min="1"
                max="500"
                onChange={(v) => setDraft({ ...draft, max_per_trade_usdc: v })}
              />
              <FieldNumber
                label={`Max per trade % equity (0.5–10, now ${fmtPct(detail.max_per_trade_pct)})`}
                value={draft.max_per_trade_pct}
                step="0.5"
                min="0.5"
                max="10"
                onChange={(v) => setDraft({ ...draft, max_per_trade_pct: v })}
              />

              {showCryptoShortFields && (
                <>
                  <FieldSelect
                    label={`Timeframe (now ${detail.selected_timeframe ?? "—"})`}
                    value={draft.selected_timeframe}
                    options={TIMEFRAMES}
                    placeholder={detail.selected_timeframe ?? "(unchanged)"}
                    onChange={(v) => setDraft({ ...draft, selected_timeframe: v })}
                  />
                  <div>
                    <p className="font-hud text-[8px] tracking-[1.5px] uppercase text-ink-4 mb-1">
                      Assets (now {(detail.selected_assets ?? []).join(", ") || "—"})
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {CRYPTO_ASSETS.map((asset) => {
                        const active = effectiveAssets.includes(asset);
                        return (
                          <button
                            key={asset}
                            type="button"
                            onClick={() => toggleAsset(asset)}
                            className={`font-mono text-[11px] px-2.5 py-1 rounded-sm border ${
                              active
                                ? "bg-gold/80 text-ink-1 border-gold"
                                : "bg-surface-2 text-ink-3 border-surface-3 hover:text-ink-1"
                            }`}
                          >
                            {asset}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Recent activity — last 5 trades */}
            <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-gold mt-5 mb-2">
              Recent Trades
            </p>
            {detail.recent_trades.length === 0 ? (
              <p className="font-mono text-[11px] text-ink-4">No trades yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {detail.recent_trades.map((t) => (
                  <RecentTradeRow key={t.id} t={t} />
                ))}
              </ul>
            )}

            {/* Recent audit log */}
            <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-gold mt-4 mb-2">
              Recent Audit
            </p>
            {detail.recent_audit.length === 0 ? (
              <p className="font-mono text-[11px] text-ink-4">No audit entries.</p>
            ) : (
              <ul className="space-y-1">
                {detail.recent_audit.map((a, i) => (
                  <RecentAuditRow key={`${a.ts}-${i}`} a={a} />
                ))}
              </ul>
            )}
          </>
        )}
        </div>

        {/* === sticky footer === always visible Save/Cancel, mobile-safe */}
        {detail && (
          <div className="flex items-center justify-between gap-2 p-3 border-t border-surface-3 bg-surface flex-shrink-0">
            <p className="font-mono text-[10px] text-ink-4 truncate min-w-0">
              {savedNote ?? "Edits are audit-logged."}
            </p>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                type="button"
                onClick={onClose}
                className="font-mono text-[11px] text-ink-3 hover:text-ink-1 px-3 py-2"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving}
                className="font-mono text-[11px] text-ink-1 bg-gold/90 hover:bg-gold disabled:opacity-50 px-4 py-2 rounded-sm"
              >
                  {saving ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-2 border border-surface-3 rounded-sm px-2.5 py-1.5">
      <p className="font-hud text-[8px] tracking-[1px] uppercase text-ink-4">{label}</p>
      <p className="font-mono text-[13px] text-ink-1 mt-0.5 truncate" title={value}>{value}</p>
    </div>
  );
}

function FieldSelect({
  label, value, options, placeholder, onChange,
}: {
  label: string;
  value: string;
  options: readonly string[];
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <p className="font-hud text-[8px] tracking-[1.5px] uppercase text-ink-4 mb-1">{label}</p>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface-2 border border-surface-3 text-ink-1 font-mono text-[12px] px-2 py-1.5 rounded-sm"
      >
        <option value="">{placeholder ?? "—"}</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </label>
  );
}

function FieldNumber({
  label, value, step, min, max, onChange,
}: {
  label: string;
  value: string;
  step?: string;
  min?: string;
  max?: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <p className="font-hud text-[8px] tracking-[1.5px] uppercase text-ink-4 mb-1">{label}</p>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value)}
        placeholder="(unchanged)"
        className="w-full bg-surface-2 border border-surface-3 text-ink-1 font-mono text-[12px] px-2 py-1.5 rounded-sm"
      />
    </label>
  );
}

function RecentTradeRow({ t }: { t: AdminRecentTrade }) {
  const pnl = t.pnl_usdc;
  const pnlColor = pnl == null
    ? "text-ink-3"
    : pnl > 0 ? "text-green" : pnl < 0 ? "text-red" : "text-ink-3";
  const pnlText = pnl == null ? "—" : `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}`;
  const sideColor = t.side === "YES" ? "text-green" : t.side === "NO" ? "text-red" : "text-ink-3";
  const market = t.market_question || "—";
  return (
    <li className="bg-surface-2 border border-surface-3 rounded-sm px-2.5 py-1.5">
      <div className="flex items-center justify-between gap-2">
        <p className="font-mono text-[11px] text-ink-1 truncate min-w-0" title={market}>
          {market}
        </p>
        <span className={`font-mono text-[11px] font-bold flex-shrink-0 ${pnlColor}`}>{pnlText}</span>
      </div>
      <div className="flex items-center justify-between gap-2 mt-0.5">
        <p className="font-mono text-[9px] text-ink-4">
          <span className={`font-bold ${sideColor}`}>{t.side ?? "—"}</span>
          {" · "}{t.status}
          {t.exit_reason ? ` · ${t.exit_reason}` : ""}
          {t.strategy_type ? ` · ${t.strategy_type}` : ""}
        </p>
        <p className="font-mono text-[9px] text-ink-4 flex-shrink-0">{relTime(t.ts)}</p>
      </div>
    </li>
  );
}

function RecentAuditRow({ a }: { a: AdminRecentAudit }) {
  return (
    <li className="flex items-center justify-between gap-2 bg-surface-2 border border-surface-3 rounded-sm px-2.5 py-1">
      <p className="font-mono text-[10px] text-ink-1 truncate min-w-0" title={a.action}>
        <span className="text-ink-4">{a.actor_role}</span>{" · "}{a.action}
      </p>
      <p className="font-mono text-[9px] text-ink-4 flex-shrink-0">{relTime(a.ts)}</p>
    </li>
  );
}
