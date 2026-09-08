"use client";

import { useEffect, useRef, useState } from "react";

import {
  ProfilePatchSchema,
  ProfileResponseSchema,
  type Profile,
  type ProfileEntry,
} from "@/lib/contracts";
import { Button } from "@/components/ui/button";
import { ProfileListField } from "@/components/profile-list-field";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

type Draft = {
  roles: string[];
  stacks: string[];
  seniority: string[];
  geographies: string[];
  remote: "" | "true" | "false";
  salary: string;
  redFlags: string[];
  preferences: string;
  brain: "ollama" | "codex";
};

type ProfileFieldsProps = {
  draft: Draft;
  busy: boolean;
  onChange: <K extends keyof Draft>(field: K, value: Draft[K]) => void;
  onSave: (entry: unknown, label: string) => void;
};

const inputClass = "mt-2 w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function draftFrom(profile: Profile): Draft {
  return {
    roles: profile["candidate.roles_wanted"],
    stacks: profile["candidate.stacks"],
    seniority: profile["candidate.seniority"],
    geographies: profile["candidate.open_to.geographies"],
    remote: profile["candidate.remote"] === null
      ? ""
      : profile["candidate.remote"] ? "true" : "false",
    salary: profile["candidate.salary_floor"] === null ? "" : String(profile["candidate.salary_floor"]),
    redFlags: profile["candidate.red_flag_words"],
    preferences: profile["candidate.preferences.free_text"] ?? "",
    brain: profile["runtime.brain"],
  };
}

function mergeSavedField(current: Draft, profile: Profile, field: ProfileEntry["field"]): Draft {
  const saved = draftFrom(profile);
  switch (field) {
    case "candidate.roles_wanted": return { ...current, roles: saved.roles };
    case "candidate.stacks": return { ...current, stacks: saved.stacks };
    case "candidate.seniority": return { ...current, seniority: saved.seniority };
    case "candidate.open_to.geographies": return { ...current, geographies: saved.geographies };
    case "candidate.remote": return { ...current, remote: saved.remote };
    case "candidate.salary_floor": return { ...current, salary: saved.salary };
    case "candidate.red_flag_words": return { ...current, redFlags: saved.redFlags };
    case "candidate.preferences.free_text": return { ...current, preferences: saved.preferences };
    case "runtime.brain": return { ...current, brain: saved.brain };
  }
}

async function profileRequest(
  method: "GET" | "PATCH",
  signal: AbortSignal,
  body?: unknown,
): Promise<Profile> {
  const response = await fetch("/api/profile", {
    method,
    cache: "no-store",
    signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(response.status === 503
      ? "The profile store is unavailable. Try again shortly."
      : "The profile request could not be completed.");
  }
  const parsed = ProfileResponseSchema.safeParse(await response.json());
  if (!parsed.success) throw new Error("The profile response was invalid.");
  return parsed.data.profile;
}

function Field({ label, busy, children }: { label: string; busy: boolean; children: React.ReactNode }) {
  return <fieldset className="rounded-xl border p-4" disabled={busy}>
    <legend className="sr-only">{label} editor</legend>
    {children}
  </fieldset>;
}

function ProfileFields({ draft, busy, onChange, onSave }: ProfileFieldsProps) {
  return <>
    <ProfileListField id="profile-roles" label="Roles wanted" description="Job titles and role families you want to find." placeholder="e.g. Product Engineer" emptyHint="No target roles added yet." value={draft.roles} busy={busy} onChange={(value) => onChange("roles", value)} onSave={(value) => onSave({ field: "candidate.roles_wanted", value }, "Roles wanted")} />
    <ProfileListField id="profile-stacks" label="Technology priorities" description="Technologies to prioritize when matching jobs. This is not a proficiency rating." placeholder="e.g. TypeScript" emptyHint="No technology priorities added yet." value={draft.stacks} busy={busy} onChange={(value) => onChange("stacks", value)} onSave={(value) => onSave({ field: "candidate.stacks", value }, "Technology priorities")} />
    <ProfileListField id="profile-seniority" label="Target role levels" description="Role levels to keep for future and manual search guidance. Leaving this empty does not reject any level." placeholder="e.g. Senior" emptyHint="Any role level can be considered." value={draft.seniority} busy={busy} onChange={(value) => onChange("seniority", value)} onSave={(value) => onSave({ field: "candidate.seniority", value }, "Target role levels")} />
    <ProfileListField id="profile-geographies" label="Open geographies" description="Countries, regions, or time zones where you would consider a role." placeholder="e.g. Israel" emptyHint="No geographic preferences added yet." value={draft.geographies} busy={busy} onChange={(value) => onChange("geographies", value)} onSave={(value) => onSave({ field: "candidate.open_to.geographies", value }, "Open geographies")} />
    <Field label="Remote preference" busy={busy}>
      <label htmlFor="profile-remote" className="text-sm font-medium">Remote preference</label>
      <select id="profile-remote" value={draft.remote} onChange={(event) => onChange("remote", event.target.value as Draft["remote"])} className={inputClass}>
        <option value="">Unknown</option><option value="true">Open to remote</option><option value="false">Not remote</option>
      </select>
      <Button type="button" variant="outline" className="mt-3" onClick={() => onSave({ field: "candidate.remote", value: draft.remote === "" ? null : draft.remote === "true" }, "Remote preference")}>Save remote preference</Button>
    </Field>
    <Field label="Salary floor" busy={busy}>
      <label htmlFor="profile-salary" className="text-sm font-medium">Salary floor</label>
      <input id="profile-salary" type="number" min="0" value={draft.salary} onChange={(event) => onChange("salary", event.target.value)} placeholder="Unknown" className={inputClass} />
      <Button type="button" variant="outline" className="mt-3" onClick={() => onSave({ field: "candidate.salary_floor", value: draft.salary === "" ? null : Number(draft.salary) }, "Salary floor")}>Save salary floor</Button>
    </Field>
    <ProfileListField id="profile-red-flags" label="Red flag words" description="Words or phrases that may signal a poor fit and deserve attention." placeholder="e.g. commission only" emptyHint="No red flag words added yet." value={draft.redFlags} busy={busy} onChange={(value) => onChange("redFlags", value)} onSave={(value) => onSave({ field: "candidate.red_flag_words", value }, "Red flag words")} />
    <Field label="Free-text preferences" busy={busy}>
      <label htmlFor="profile-preferences" className="text-sm font-medium">Free-text preferences</label>
      <p className="mt-1 text-xs text-muted-foreground">Personal job-fit guidance for your search, such as the work, team, or company environment you prefer. This guidance is included when assessing job fit.</p>
      <textarea id="profile-preferences" maxLength={2000} value={draft.preferences} onChange={(event) => onChange("preferences", event.target.value)} placeholder="e.g. I prefer product teams with close customer contact." className={`${inputClass} min-h-28`} />
      <Button type="button" variant="outline" className="mt-3" onClick={() => onSave({ field: "candidate.preferences.free_text", value: draft.preferences.trim() || null }, "Free-text preferences")}>Save preferences</Button>
    </Field>
    <Field label="Extraction brain" busy={busy}>
      <label htmlFor="profile-brain" className="text-sm font-medium">Extraction brain</label>
      <p className="mt-1 text-xs text-muted-foreground">Classifier runs select their own brain independently.</p>
      <select id="profile-brain" value={draft.brain} onChange={(event) => onChange("brain", event.target.value as Draft["brain"])} className={inputClass}>
        <option value="ollama">Ollama</option><option value="codex">Codex</option>
      </select>
      <Button type="button" className="mt-3" onClick={() => onSave({ field: "runtime.brain", value: draft.brain }, "Extraction brain")}>Save extraction brain</Button>
    </Field>
  </>;
}

function DrawerHeader() {
  return <SheetHeader className="border-b p-6 pr-12">
    <SheetTitle>Profile and extraction</SheetTitle>
    <SheetDescription>Save one field at a time so unrelated profile updates stay intact.</SheetDescription>
  </SheetHeader>;
}

function ProfileStatus({ loading, saving, success, error, retry }: {
  loading: boolean;
  saving: boolean;
  success: string;
  error: string;
  retry: (() => void) | null;
}) {
  return <>
    <div aria-live="polite" className="min-h-5 text-sm">
      {loading ? <span className="text-muted-foreground">Loading the latest profile…</span> : null}
      {saving ? <span className="text-muted-foreground">Saving…</span> : null}
      {success ? <span className="text-foreground">{success}</span> : null}
    </div>
    {error ? <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
      {error}
      {retry ? <Button type="button" variant="outline" className="ml-3" onClick={retry}>Retry</Button> : null}
    </div> : null}
  </>;
}

function DrawerBody({ draft, busy, loading, saving, success, error, retry, onChange, onSave }: {
  draft: Draft | null;
  busy: boolean;
  loading: boolean;
  saving: boolean;
  success: string;
  error: string;
  retry: () => void;
  onChange: ProfileFieldsProps["onChange"];
  onSave: ProfileFieldsProps["onSave"];
}) {
  return <div className="space-y-4 p-6" aria-busy={busy}>
    <ProfileStatus loading={loading} saving={saving} success={success} error={error} retry={draft === null ? retry : null} />
    {draft === null ? null : <ProfileFields draft={draft} busy={busy} onChange={onChange} onSave={onSave} />}
  </div>;
}

export function ProfileDrawer({ onUpdated }: { onUpdated: () => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingField, setSavingField] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const requestVersion = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => () => {
    requestVersion.current += 1;
    activeRequest.current?.abort();
  }, []);

  function start(promise: Promise<unknown>) {
    promise.catch(() => undefined);
  }

  async function loadProfile() {
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setDraft(null);
    setLoading(true);
    setSavingField(null);
    setError("");
    setSuccess("");
    try {
      const profile = await profileRequest("GET", controller.signal);
      if (version === requestVersion.current && !controller.signal.aborted) {
        setDraft(draftFrom(profile));
      }
    } catch (cause) {
      if (version === requestVersion.current && !controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "The profile could not be loaded.");
      }
    } finally {
      if (version === requestVersion.current && !controller.signal.aborted) setLoading(false);
    }
  }

  function changeOpen(next: boolean) {
    setOpen(next);
    if (next) start(loadProfile());
    else {
      requestVersion.current += 1;
      activeRequest.current?.abort();
    }
  }

  async function save(entry: unknown, label: string) {
    if (!draft || savingField) return;
    const parsed = ProfilePatchSchema.safeParse(entry);
    if (!parsed.success) {
      setError(`Check the ${label.toLowerCase()} value and try again.`);
      setSuccess("");
      return;
    }
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setSavingField(parsed.data.field);
    setError("");
    setSuccess("");
    let updated = false;
    try {
      const profile = await profileRequest("PATCH", controller.signal, parsed.data);
      if (version === requestVersion.current && !controller.signal.aborted) {
        setDraft((current) => current === null
          ? draftFrom(profile)
          : mergeSavedField(current, profile, parsed.data.field));
        setSuccess(`${label} saved.`);
        updated = true;
      }
    } catch (cause) {
      if (version === requestVersion.current && !controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : `${label} could not be saved.`);
      }
    } finally {
      if (version === requestVersion.current && !controller.signal.aborted) setSavingField(null);
    }
    if (updated) onUpdated();
  }

  function updateDraft<K extends keyof Draft>(field: K, value: Draft[K]) {
    setDraft((current) => current === null ? current : { ...current, [field]: value });
  }

  function startSave(entry: unknown, label: string) {
    start(save(entry, label));
  }

  const busy = loading || savingField !== null;
  return <>
    <Button ref={triggerRef} type="button" variant="outline" onClick={() => changeOpen(true)}>Edit profile</Button>
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent finalFocus={triggerRef} className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
        <DrawerHeader />
        <DrawerBody draft={draft} busy={busy} loading={loading} saving={savingField !== null} success={success} error={error} retry={() => start(loadProfile())} onChange={updateDraft} onSave={startSave} />
      </SheetContent>
    </Sheet>
  </>;
}
