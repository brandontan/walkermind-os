import { useCallback, useState } from "react";
import { Toggle } from "./Toggle";

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

export type NotifPrefs = Record<PrefKey, boolean>;

const DEFAULT_PREFS: NotifPrefs = {
  trade_opened: true,
  trade_closed: true,
  position_resolved: true,
  signal_detected: true,
  system_status: true,
  bot_errors: true,
  kill_switch: true,
  low_balance: true,
  daily_report: true,
};

export const NOTIF_PREFS_KEY = "notif_prefs";

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
      { key: "trade_opened",      name: "Trade Opened",      desc: "Alert when a new position is entered"              },
      { key: "trade_closed",      name: "Trade Closed",      desc: "Alert on take-profit, stop-loss, or expiry"        },
      { key: "position_resolved", name: "Position Resolved", desc: "Win/loss notification when market settles"         },
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
      { key: "system_status", name: "System Status",       desc: "Bot online/offline & connectivity changes"         },
      { key: "bot_errors",    name: "Bot Errors",          desc: "Critical errors that require attention"            },
      { key: "kill_switch",   name: "Kill Switch Triggered", desc: "Alert when emergency stop activates"            },
      { key: "low_balance",   name: "Low Balance",         desc: "Notify when wallet balance drops below threshold"  },
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

export function loadNotifPrefs(): NotifPrefs {
  try {
    const raw = localStorage.getItem(NOTIF_PREFS_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...(JSON.parse(raw) as Partial<NotifPrefs>) };
  } catch { /* ignore */ }
  return { ...DEFAULT_PREFS };
}

function saveNotifPrefs(p: NotifPrefs) {
  try { localStorage.setItem(NOTIF_PREFS_KEY, JSON.stringify(p)); } catch { /* quota */ }
}

export function NotificationPrefsCard() {
  const [prefs, setPrefs] = useState<NotifPrefs>(loadNotifPrefs);

  const enabledCount = ALL_KEYS.filter((k) => prefs[k]).length;
  const totalCount = ALL_KEYS.length;

  const setOne = useCallback((key: PrefKey, value: boolean) => {
    setPrefs((p) => {
      const next = { ...p, [key]: value };
      saveNotifPrefs(next);
      return next;
    });
  }, []);

  const setAll = useCallback((value: boolean) => {
    setPrefs(() => {
      const next = Object.fromEntries(ALL_KEYS.map((k) => [k, value])) as NotifPrefs;
      saveNotifPrefs(next);
      return next;
    });
  }, []);

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
            {enabledCount}/{totalCount} ALERTS ENABLED
          </p>
        </div>
        <div className="flex gap-1.5 flex-shrink-0">
          <button
            type="button"
            onClick={() => setAll(true)}
            className="font-mono text-[9px] font-bold tracking-[1.5px] uppercase px-3 py-1.5 rounded border transition-colors"
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
            className="font-mono text-[9px] font-bold tracking-[1.5px] uppercase px-3 py-1.5 rounded border transition-colors"
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

      {/* Gold rule */}
      <div className="h-px mb-3 mx-1" style={{ background: "var(--gold)", opacity: 0.25 }} />

      {/* Category sections */}
      <div className="space-y-3">
        {CATEGORIES.map((cat) => {
          const catKeys = cat.items.map((i) => i.key);
          const catEnabled = catKeys.filter((k) => prefs[k]).length;
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
                {cat.items.map((item, idx) => (
                  <div
                    key={item.key}
                    className="flex items-center gap-3 px-3 py-3"
                    style={idx > 0 ? { borderTop: "1px solid var(--border-1)" } : undefined}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="font-sans text-[12px] font-semibold text-ink-1">
                          {item.name}
                        </span>
                        <span
                          className="font-mono text-[8px] font-bold px-1.5 py-0.5 rounded"
                          style={
                            prefs[item.key]
                              ? {
                                  background: "rgba(0,255,156,0.15)",
                                  color: "var(--grn,#00FF9C)",
                                  border: "1px solid rgba(0,255,156,0.3)",
                                }
                              : {
                                  background: "rgba(255,255,255,0.05)",
                                  color: "var(--ink-4)",
                                  border: "1px solid var(--border-2)",
                                }
                          }
                        >
                          {prefs[item.key] ? "ON" : "OFF"}
                        </span>
                      </div>
                      <p className="font-mono text-[10px] text-ink-3 leading-snug">{item.desc}</p>
                    </div>
                    <Toggle
                      checked={prefs[item.key]}
                      onChange={(v) => setOne(item.key, v)}
                      ariaLabel={`Toggle ${item.name}`}
                    />
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
