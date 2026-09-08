"use client";

import Image from "next/image";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { companyInitials, logoPathForCompany } from "@/lib/company-logos";

type CompanyLogoProps = {
  company: string;
  className?: string;
};

export function CompanyLogo({ company, className }: CompanyLogoProps) {
  const src = logoPathForCompany(company);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const frame = cn("grid size-11 shrink-0 place-items-center overflow-hidden rounded-xl border bg-white", className);

  if (!src || failedSrc === src) {
    return <span role="img" aria-label={`${company} logo unavailable`} data-logo-state={src ? "load-failed" : "unmapped"} className={cn(frame, "text-sm font-bold text-slate-700")}>{companyInitials(company)}</span>;
  }

  return <span className={frame}><Image unoptimized src={src} alt={`${company} logo`} width={44} height={44} className="size-full object-contain" onError={() => setFailedSrc(src)} /></span>;
}
