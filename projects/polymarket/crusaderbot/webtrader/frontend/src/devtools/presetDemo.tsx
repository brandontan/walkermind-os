// Dev/e2e harness — renders the REAL /admin preset dropdown (FieldSelect +
// PRESET_OPTIONS from AdminUserDrawer) so e2e/preset-dropdown.spec.ts can assert
// the option set and capture the before/after screenshot CMD requested. Not wired
// into the app router; served only on the Vite dev server at /preset-demo.html.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { FieldSelect, PRESET_OPTIONS } from "../components/AdminUserDrawer";
import "../index.css";

// The stale hardcoded list this PR replaced (before/after visual only).
const BEFORE = ["close_sweep", "safe_close", "flip_hunter", "weather_monitor"];

const listBox: React.CSSProperties = {
  background: "#0b0e14",
  color: "#e6e8ee",
  border: "1px solid #2a2f3a",
  fontFamily: "monospace",
  fontSize: 12,
  padding: 6,
  minWidth: 420,
};

function Demo() {
  return (
    <div style={{ padding: 24, background: "#05070b", minHeight: "100vh" }}>
      {/* The real component under test. */}
      <div data-testid="field" style={{ width: 380, marginBottom: 28 }}>
        <FieldSelect
          label="Active preset"
          value=""
          options={PRESET_OPTIONS}
          placeholder="(unchanged)"
          onChange={() => {}}
        />
      </div>

      {/* Before/after visual (open listboxes so every option is captured). */}
      <div data-testid="before-after" style={{ display: "flex", gap: 24 }}>
        <div>
          <p style={{ color: "#f0b429", fontFamily: "monospace", fontSize: 11 }}>
            BEFORE — missing candle_auto + playbook
          </p>
          <select size={BEFORE.length + 1} style={listBox}>
            <option value="">(unchanged)</option>
            {BEFORE.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
        <div>
          <p style={{ color: "#3fb950", fontFamily: "monospace", fontSize: 11 }}>
            AFTER — canonical registry (6 presets)
          </p>
          <select size={PRESET_OPTIONS.length + 1} style={listBox}>
            <option value="">(unchanged)</option>
            {PRESET_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Demo />
  </StrictMode>,
);
