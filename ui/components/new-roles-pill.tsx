import { ArrowUp } from "lucide-react";
import { newRolesLabel } from "@/lib/new-roles";

// A zero-height sticky slot: the pill floats over the list and never shifts it.
export function NewRolesPill({ count, truncated, onShow }: { count: number; truncated: boolean; onShow: () => void }) {
  return <div role="status" className="pointer-events-none sticky top-3 z-20 flex h-0 justify-center">
    {count > 0 && <button type="button" data-new-roles onClick={onShow} className="pointer-events-auto inline-flex h-8 -translate-y-1/2 items-center gap-1.5 rounded-full bg-primary px-3.5 text-xs font-medium text-primary-foreground shadow-lg ring-1 ring-foreground/10 transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 animate-in fade-in slide-in-from-top-1 motion-reduce:animate-none">
      <ArrowUp aria-hidden="true" className="size-3.5" />{newRolesLabel(count, truncated)}<span aria-hidden="true">·</span><span className="font-semibold underline-offset-2 group-hover:underline">Show</span>
    </button>}
  </div>;
}
