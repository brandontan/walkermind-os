import { useCallback, useEffect, useMemo, useState } from "react";
import type { NotificationPrefs, NotificationChannelPrefs } from "../lib/api";
import { makeApi } from "../lib/api";
import { useAuth } from "../lib/auth";

// Alert keys must match the backend ALERT_KEYS frozenset exactly.
type PrefKey =
  | "trade_opened"
  | "trade_closed"
  | "position_resolved"
  | "signal_detected"
  | "system_status"
  | "bot_errors"
  | "kill_switch"
  | "low_balance"
  | "daily_report";

type CategoryDef = {
  id: string;
  label: string;
  icon: string;
  color: string;
  bg: string;
  border: string;
  items: { key: PrefKey; name: string; desc: string }[];
};

const CATEGORIES: CategoryDef[] = [
  {
    id: "TRADING",
    label: "TRADING",
    icon: "⚡",
    color: "var(--gold)",
    bg: "rgba(245,200,66,0.08)",
    border: "rgba(245,200,66,0.2)",
    items: [
      { key: "trade_opened",      name: "Trade Opened",      desc: "Alert when a new position is entered"      },
      { key: "trade_closed",      name: "Trade Closed",      desc: "Alert on take-profit, stop-loss, or expiry" },
      { key: "position_resolved", name: "Position Resolved", desc: "Win/loss notification when market settles" },
    ],
  },
  {
    id: "SIGNALS",
    label: "SIGNALS",
    icon: "📡",
    color: "var(--cyan)",
    bg: "rgba(0,212,255,0.06)",
    border: "rgba(0,212,255,0.2)",
    items: [
      { key: "signal_detected", name: "Signal Detected", desc: "New high-confidence signal found by scanner" },
    ],
  },
  {
    id: "SYSTEM",
    label: "SYSTEM",
    icon: "🖥",
    color: "var(--ink-2)",
    bg: "rgba(255,255,255,0.04)",
    border: "rgba(255,255,255,0.1)",
    items: [
      { key: "system_status", name: "System Status",         desc: "Bot online/offline & connectivity changes"        },
      { key: "bot_errors",    name: "Bot Errors",            desc: "Critical errors that require attention"           },
      { key: "kill_switch",   name: "Kill Switch Triggered", desc: "Alert when emergency stop activates"              },
      { key: "low_balance",   name: "Low Balance",           desc: "Notify when wallet balance drops below threshold" },
    ],
  },
  {
    id: "REPORTS",
    label: "REPORTS",
    icon: "📊",
    color: "var(--grn)",
    bg: "rgba(0,255,156,0.06)",
    border: "rgba(0,255,156,0.15)",
    items: [
      { key: "daily_report", name: "Daily P&L Report", desc: "End-of-day summary delivered via Telegram" },
    ],
  },
];

const ALL_KEYS: PrefKey[] = CATEGORIES.flatMap((c) => c.items.map((i) => i.key));

// "Channel ON" means: pref is undefined (server default) OR explicitly true.
function isChannelOn(row: NotificationChannelPrefs | undefined, channel: "web" | "tg"): boolean {
  if (!row) return true;
  const v = row[channel];
  return v === undefined ? true : !!v;
}

// "Alert ON" means: at least one channel is enabled. Mirrors the gate logic
// — a notification fires when either channel is active.
function isAlertOn(prefs: NotificationPrefs, key: PrefKey): boolean {
  const row = prefs[key];
  return isChannelOn(row, "web") || isChannelOn(row, "tg");
}

function makeBothOff(): NotificationChannelPrefs {
  return { web: false, tg: false };
}

function makeBothOn(): NotificationChannelPrefs {
  return { web: true, tg: true };
}

export function NotificationPrefsCard() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [prefs, setPrefs] = useState<NotificationPrefs>({});
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initial load from server.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.getNotificationPrefs();
        if (cancelled) return;
        setPrefs(res.prefs ?? {});
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load preferences");
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [api]);

  // Persist on every change — debounced to one in-flight request at a time.
  const persist = useCallback(async (next: NotificationPrefs) => {
    setSaving(true);
    try {
      await api.updateNotificationPrefs(next);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save preferences");
    } finally {
      setSaving(false);
    }
  }, [api]);

  const setChannel = useCallback((key: PrefKey, channel: "web" | "tg", value: boolean) => {
    setPrefs((p) => {
      const row = { ...(p[key] ?? makeBothOn()) };
      row[channel] = value;
      const next = { ...p, [key]: row };
      void persist(next);
      return next;
    });
  }, [persist]);

  const setAll = useCallback((value: boolean) => {
    setPrefs(() => {
      const next: NotificationPrefs = Object.fromEntries(
        ALL_KEYS.map((k) => [k, value ? makeBothOn() : makeBothOff()]),
      );
      void persist(next);
      return next;
    });
  }, [persist]);

  const enabledCount = ALL_KEYS.filter((k) => isAlertOn(prefs, k)).length;
  const totalCount = ALL_KEYS.length;

  return (
    <div className="mb-4">
      {/* Header row */}
      <div className="flex items-start justify-between mb-3 px-1">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-1 h-5 rounded-full flex-shrink-0" style={{ background: "var(--gold)" }} />
            <span className="font-hud text-[13px] font-bold tracking-[3px] uppercase text-ink-1">
              Notification Preferences
            </span>
          </div>
          <p className="font-mono text-[10px] text-ink-3 mt-1 pl-3">
            {loaded
              ? `${enabledCount}/${totalCount} ALERTS ENABLED${saving ? " · SAVING…" : ""}`
              : "LOADING…"}
            {error && <span className="text-red ml-2">· {error}</span>}
          </p>
        </div>
        <div className="flex gap-1.5 flex-shrink-0">
          <button
            type="button"
            onClick={() => setAll(true)}
            disabled={!loaded}
            className="font-mono text-[9px] font-bold tracking-[1.5px] uppercase px-3 py-1.5 rounded border transition-colors disabled:opacity-50"
            style={{
              background: "rgba(245,200,66,0.08)",
              borderColor: "rgba(245,200,66,0.3)",
              color: "var(--gold)",
            }}
          >
            All On
          </button>
          <button
            type="button"
            onClick={() => setAll(false)}
            disabled={!loaded}
            className="font-mono text-[9px] font-bold tracking-[1.5px] uppercase px-3 py-1.5 rounded border transition-colors disabled:opacity-50"
            style={{
              background: "var(--surface-3)",
              borderColor: "var(--border-2)",
              color: "var(--ink-3)",
            }}
          >
            All Off
          </button>
        </div>
      </div>

      {/* Channel legend — explains the two chip styles per row */}
      <div className="flex items-center gap-3 mb-2 px-1 font-mono text-[9px] text-ink-4 tracking-[1px] uppercase">
        <span>Channels:</span>
        <span className="inline-flex items-center gap-1">
          <span>📡</span> Web
        </span>
        <span className="inline-flex items-center gap-1">
          <span>💬</span> TG
        </span>
        <span className="opacity-50">· tap to toggle each</span>
      </div>

      {/* Gold rule */}
      <div className="h-px mb-3 mx-1" style={{ background: "var(--gold)", opacity: 0.25 }} />

      {/* Category sections */}
      <div className="space-y-3">
        {CATEGORIES.map((cat) => {
          const catKeys = cat.items.map((i) => i.key);
          const catEnabled = catKeys.filter((k) => isAlertOn(prefs, k)).length;
          return (
            <div
              key={cat.id}
              className="rounded-lg overflow-hidden"
              style={{ border: "1px solid var(--border-2)" }}
            >
              {/* Category header */}
              <div
                className="flex items-center justify-between px-3 py-2.5"
                style={{ background: cat.bg, borderBottom: `1px solid ${cat.border}` }}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[13px]" aria-hidden>{cat.icon}</span>
                  <span
                    className="font-hud text-[11px] font-bold tracking-[2px] uppercase"
                    style={{ color: cat.color }}
                  >
                    {cat.label}
                  </span>
                </div>
                <span
                  className="font-mono text-[9px] font-bold"
                  style={{ color: cat.color, opacity: 0.7 }}
                >
                  {catEnabled}/{catKeys.length} ON
                </span>
              </div>

              {/* Items */}
              <div style={{ background: "var(--surface-2)" }}>
                {cat.items.map((item, idx) => {
                  const row = prefs[item.key];
                  const webOn = isChannelOn(row, "web");
                  const tgOn  = isChannelOn(row, "tg");
                  return (
                    <div
                      key={item.key}
                      className="flex items-center gap-3 px-3 py-3"
                      style={idx > 0 ? { borderTop: "1px solid var(--border-1)" } : undefined}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-sans text-[12px] font-semibold text-ink-1 mb-0.5">
                          {item.name}
                        </div>
                        <p className="font-mono text-[10px] text-ink-3 leading-snug">{item.desc}</p>
                      </div>
                      <div className="flex gap-1.5 flex-shrink-0">
                        <ChannelChip
                          icon="📡"
                          label="WEB"
                          on={webOn}
                          onClick={() => setChannel(item.key, "web", !webOn)}
                          disabled={!loaded}
                        />
                        <ChannelChip
                          icon="💬"
                          label="TG"
                          on={tgOn}
                          onClick={() => setChannel(item.key, "tg", !tgOn)}
                          disabled={!loaded}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChannelChip({
  icon, label, on, onClick, disabled,
}: {
  icon: string;
  label: string;
  on: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={on}
      aria-label={`Toggle ${label} channel`}
      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded border font-mono text-[9px] font-bold tracking-[1.5px] uppercase transition-colors disabled:opacity-50"
      style={
        on
          ? {
              background: "rgba(0,255,156,0.12)",
              borderColor: "rgba(0,255,156,0.4)",
              color: "var(--grn,#00FF9C)",
            }
          : {
              background: "rgba(255,255,255,0.03)",
              borderColor: "var(--border-2)",
              color: "var(--ink-4)",
            }
      }
    >
      <span aria-hidden>{icon}</span>
      {label}
    </button>
  );
}
