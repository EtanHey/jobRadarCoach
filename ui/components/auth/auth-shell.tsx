import type { ReactNode } from "react";

import { AuthSystemTheme } from "./auth-system-theme";

export function AuthShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <AuthSystemTheme />
      <section className="w-full max-w-sm rounded-2xl border bg-card p-7 shadow-sm">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-primary">Job Radar Coach</p>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <div className="mt-6">{children}</div>
      </section>
    </main>
  );
}
