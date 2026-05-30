import { useEffect, useMemo, useState } from "react";
import type { AdminUserDetail, AdminUserPatch } from "../lib/api";
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

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
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
  }>({
    active_preset: "",
    risk_profile: "",
    capital_alloc_pct: "",
    tp_pct: "",
    sl_pct: "",
    max_per_trade_mode: "",
    max_per_trade_usdc: "",
    max_per_trade_pct: "",
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
      setSavedNote("Saved.");
      onSaved?.(next);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg.replace(/^\d+:\s*/, ""));
    } finally {
      setSaving(false);
    }
  }

  const label = detail
    ? (detail.username ? `@${detail.username}` : (detail.email ?? detail.user_id.slice(0, 8)))
    : userId.slice(0, 8);

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
            <div className="grid grid-cols-2 gap-2 mb-4">
              <Stat label="Mode" value={detail.trading_mode.toUpperCase()} />
              <Stat label="Auto" value={detail.paused ? "PAUSED" : detail.auto_trade_on ? "ON" : "OFF"} />
              <Stat label="Balance" value={fmtUsd(detail.balance_usdc)} />
              <Stat label="Open positions" value={String(detail.open_positions)} />
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
                label={`TP % (0.5–1000, now ${fmtPct(detail.tp_pct)})`}
                value={draft.tp_pct}
                step="0.5"
                min="0.5"
                max="1000"
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
            </div>
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
      <p className="font-mono text-[13px] text-ink-1 mt-0.5">{value}</p>
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
