"use client";

import { useEffect } from "react";

import { followSystemTheme } from "../../lib/auth/system-theme";

export function AuthSystemTheme() {
  useEffect(
    () => followSystemTheme(
      document.documentElement,
      window.matchMedia("(prefers-color-scheme: dark)"),
    ),
    [],
  );
  return null;
}
