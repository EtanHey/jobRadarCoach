"use client";
import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
const key = "job-radar-theme";
export function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => { let stored: string | null = null; try { stored = localStorage.getItem(key); } catch {} const enabled = stored ? stored === "dark" : matchMedia("(prefers-color-scheme: dark)").matches; document.documentElement.classList.toggle("dark", enabled); queueMicrotask(() => setDark(enabled)); }, []);
  function toggle() { const next = !dark; document.documentElement.classList.toggle("dark", next); try { localStorage.setItem(key, next ? "dark" : "light"); } catch {} setDark(next); }
  return <button type="button" onClick={toggle} aria-label={`Use ${dark ? "light" : "dark"} theme`} className="grid size-9 place-items-center rounded-xl border bg-card text-muted-foreground transition hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2">{dark ? <Sun aria-hidden="true" size={17} /> : <Moon aria-hidden="true" size={17} />}</button>;
}
