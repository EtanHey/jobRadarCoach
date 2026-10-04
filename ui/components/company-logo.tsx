"use client";

import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";
import { companyInitials, logoDevKey, resolveCompanyLogo } from "@/lib/company-logos";
import { browserLogoMissCache } from "@/lib/company-logo-cache";

// Deliberately Next-free (plain <img>): the drawer's import graph must stay host-portable.
const sizes = { sm: "size-10 text-xs", md: "size-14 text-sm sm:size-16" } as const;

type CompanyLogoProps = {
  company: string;
  applyUrl?: string | null;
  url?: string | null;
  size?: keyof typeof sizes;
  className?: string;
};

export function CompanyLogo({ company, applyUrl, url, size = "md", className }: CompanyLogoProps) {
  const source = resolveCompanyLogo({ company, applyUrl, url }, { logoDevKey });
  // Logo.dev bills misses too; one this device already saw renders initials without asking again.
  // Cards and the drawer only render client-side (after preferences load), so reading storage here cannot mismatch hydration.
  const misses = source?.kind === "logo-dev" ? browserLogoMissCache() : null;
  const knownMiss = source !== null && misses?.isMiss(source.src) === true;
  const src = knownMiss ? null : source?.src ?? null;
  const [settled, setSettled] = useState<{ src: string; ok: boolean } | null>(null);
  const state = knownMiss ? "cached-miss" : !src ? "unmapped" : settled?.src !== src ? "loading" : settled.ok ? "loaded" : "load-failed";
  const settle = useCallback((ok: boolean) => {
    if (!src) return;
    setSettled(current => current?.src === src && current.ok === ok ? current : { src, ok });
    // Offline failures say nothing about Logo.dev, so only an online failure counts as a miss.
    if (ok) misses?.recordHit(src);
    else if (typeof navigator === "undefined" || navigator.onLine !== false) misses?.recordMiss(src);
  }, [src, misses]);
  // An image can finish before hydration attaches onLoad/onError; read its outcome on mount.
  const probe = useCallback((image: HTMLImageElement | null) => {
    if (image?.complete) settle(image.naturalWidth > 0);
  }, [settle]);
  const initials = state === "unmapped" || state === "load-failed" || state === "cached-miss";

  return <span data-company-logo="" data-logo-size={size} data-logo-state={state} data-logo-source={source?.kind} role="img" aria-label={initials ? `${company} logo unavailable` : `${company} logo`}
    className={cn("relative grid shrink-0 place-items-center overflow-hidden rounded-lg border font-bold", state === "loaded" ? "bg-white" : "bg-muted text-muted-foreground", sizes[size], className)}>
    {initials && <span aria-hidden="true">{companyInitials(company)}</span>}
    {/* eslint-disable-next-line @next/next/no-img-element -- see the Next-free note above */}
    {src && !initials && <img ref={probe} src={src} alt="" width={64} height={64} loading="lazy" decoding="async" onLoad={() => settle(true)} onError={() => settle(false)}
      className={cn("absolute inset-0 size-full bg-white object-contain p-[6%] transition-opacity duration-150 motion-reduce:transition-none", state === "loaded" ? "opacity-100" : "opacity-0")} />}
  </span>;
}

/** Logo.dev's free plan asks for a followable link (referrer intact) wherever its logos appear. */
export function LogoDevAttribution() {
  if (!logoDevKey.startsWith("pk_")) return null;
  return <p className="mt-1 text-xs text-muted-foreground">
    {/* skipcq: JS-0422 -- Logo.dev verifies attribution by referrer, so noreferrer would break it (logo.dev/docs/platform/attribution); noopener still blocks window.opener. */}
    <a href="https://logo.dev" target="_blank" rel="noopener" className="underline-offset-2 hover:underline">Logos provided by Logo.dev</a>
  </p>;
}
