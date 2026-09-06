/**
 * Dark/light theme state. The resolved mode is stamped on <html data-theme="...">,
 * which the CSS custom properties in index.css key off; charts read the same resolution
 * through `tokens`.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { tokensFor } from "./tokens";
import type { ThemeMode, ThemeTokens } from "./tokens";

type ThemePreference = ThemeMode | "system";

interface ThemeContextValue {
  preference: ThemePreference;
  mode: ThemeMode;
  tokens: ThemeTokens;
  setPreference: (preference: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = "apix-theme";

function storedPreference(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    /* storage unavailable — fall through to system */
  }
  return "system";
}

function systemMode(): ThemeMode {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(storedPreference);
  const [system, setSystem] = useState<ThemeMode>(systemMode);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSystem(systemMode());
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const mode: ThemeMode = preference === "system" ? system : preference;

  useEffect(() => {
    document.documentElement.dataset["theme"] = mode;
    document.documentElement.style.colorScheme = mode;
  }, [mode]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* storage unavailable — preference lasts the session */
    }
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ preference, mode, tokens: tokensFor(mode), setPreference }),
    [preference, mode, setPreference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) throw new Error("useTheme called outside ThemeProvider");
  return value;
}
