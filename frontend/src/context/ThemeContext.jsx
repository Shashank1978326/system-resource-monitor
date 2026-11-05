import { useCallback, useEffect, useMemo, useState } from "react";
import ThemeContext from "./themeStore";
const STORAGE_KEY = "srm-theme";

function readPreference() {
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return ["light", "dark", "system"].includes(saved) ? saved : "system";
}

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(readPreference);
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false,
  );
  const theme = preference === "system" ? (systemDark ? "dark" : "light") : preference;

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query) return undefined;
    const update = (event) => setSystemDark(event.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(STORAGE_KEY, preference);
  }, [preference, theme]);

  const toggleTheme = useCallback(() => {
    setPreference((current) => (current === "dark" ? "light" : "dark"));
  }, []);
  const value = useMemo(
    () => ({ preference, setPreference, theme, toggleTheme }),
    [preference, theme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
