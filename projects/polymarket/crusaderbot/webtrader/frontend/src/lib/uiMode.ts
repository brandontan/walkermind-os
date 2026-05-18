import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "cb_ui_advanced";

export type UiMode = {
  advanced: boolean;
  toggle: () => void;
  setAdvanced: (v: boolean) => void;
};

const defaultMode: UiMode = {
  advanced: true,
  toggle: () => {},
  setAdvanced: () => {},
};

export const UiModeContext = createContext<UiMode>(defaultMode);

export function useUiMode(): UiMode {
  return useContext(UiModeContext);
}

export function useUiModeState(): UiMode {
  // Hydrate synchronously from localStorage to avoid first-paint flicker.
  // Default ON (advanced) unless explicitly stored as "0".
  const initial = (() => {
    if (typeof window === "undefined") return true;
    try {
      return window.localStorage.getItem(STORAGE_KEY) !== "0";
    } catch {
      return true;
    }
  })();

  const [advanced, setAdvancedRaw] = useState<boolean>(initial);

  const setAdvanced = useCallback((v: boolean) => {
    setAdvancedRaw(v);
    try {
      window.localStorage.setItem(STORAGE_KEY, v ? "1" : "0");
    } catch {
      /* localStorage unavailable — silently degrade */
    }
  }, []);

  const toggle = useCallback(() => {
    setAdvanced(!advanced);
  }, [advanced, setAdvanced]);

  // Mirror state onto <body> so plain CSS rules (`.advanced .adv-only`) work.
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.body.classList.toggle("advanced", advanced);
  }, [advanced]);

  return useMemo<UiMode>(() => ({ advanced, toggle, setAdvanced }), [advanced, toggle, setAdvanced]);
}
