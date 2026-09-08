"use client";

import { useState } from "react";
import { ArrowLeft, ArrowRight, GripVertical } from "lucide-react";

import { Button } from "@/components/ui/button";
import { moveProfileItem } from "@/lib/profile-ordering";

type ProfileListFieldProps = {
  id: string;
  label: string;
  description: string;
  placeholder: string;
  emptyHint: string;
  value: string[];
  busy: boolean;
  onChange: (value: string[]) => void;
  onSave: (value: string[]) => void;
};

function appendEntries(current: string[], raw: string): string[] {
  const additions = raw.split(",").map((item) => item.trim()).filter(Boolean);
  return additions.reduce(
    (items, item) => items.includes(item) ? items : [...items, item],
    current,
  );
}

export function ProfileListField({
  id,
  label,
  description,
  placeholder,
  emptyHint,
  value,
  busy,
  onChange,
  onSave,
}: ProfileListFieldProps) {
  const [pending, setPending] = useState("");
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);

  function addPending() {
    const next = appendEntries(value, pending);
    if (next !== value) onChange(next);
    setPending("");
    return next;
  }

  function save() {
    onSave(addPending());
  }

  function move(fromIndex: number, toIndex: number) {
    onChange(moveProfileItem(value, fromIndex, toIndex));
  }

  return <fieldset className="rounded-xl border p-4" disabled={busy}>
    <legend className="sr-only">{label} editor</legend>
    <label htmlFor={id} className="text-sm font-medium">{label}</label>
    <p id={`${id}-description`} className="mt-1 text-xs text-muted-foreground">{description}</p>
    <div className="mt-3 flex min-h-9 flex-wrap gap-2" aria-live="polite">
      {value.map((item, index) => <span
        key={item}
        draggable={!busy}
        onDragStart={(event) => {
          setDraggedIndex(index);
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", item);
        }}
        onDragOver={(event) => {
          if (draggedIndex !== null && draggedIndex !== index) {
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
          }
        }}
        onDrop={(event) => {
          event.preventDefault();
          if (draggedIndex !== null) move(draggedIndex, index);
          setDraggedIndex(null);
        }}
        onDragEnd={() => setDraggedIndex(null)}
        className="inline-flex items-center gap-0.5 rounded-full border bg-muted px-1.5 py-1 text-sm text-foreground"
      >
        <GripVertical className="size-3.5 cursor-grab text-muted-foreground" aria-hidden="true" />
        <span className="px-1">{item}</span>
        <button
          type="button"
          className="rounded-full p-1 text-muted-foreground hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-30"
          aria-label={`Move ${item} earlier in ${label.toLowerCase()}`}
          onClick={() => move(index, index - 1)}
          disabled={index === 0}
        ><ArrowLeft className="size-3.5" aria-hidden="true" /></button>
        <button
          type="button"
          className="rounded-full p-1 text-muted-foreground hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-30"
          aria-label={`Move ${item} later in ${label.toLowerCase()}`}
          onClick={() => move(index, index + 1)}
          disabled={index === value.length - 1}
        ><ArrowRight className="size-3.5" aria-hidden="true" /></button>
        <button
          type="button"
          className="rounded-full p-1 text-muted-foreground hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Remove ${item} from ${label.toLowerCase()}`}
          onClick={() => onChange(value.filter((entry) => entry !== item))}
        >×</button>
      </span>)}
      {value.length === 0 ? <span className="self-center text-xs text-muted-foreground">{emptyHint}</span> : null}
    </div>
    <div className="mt-3 flex gap-2">
      <input
        id={id}
        value={pending}
        onChange={(event) => {
          const next = event.target.value;
          if (next.includes(",")) {
            const parts = next.split(",");
            const remainder = next.endsWith(",") ? "" : parts.pop() ?? "";
            onChange(appendEntries(value, parts.join(",")));
            setPending(remainder);
          } else {
            setPending(next);
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            addPending();
          }
        }}
        aria-describedby={`${id}-description`}
        placeholder={placeholder}
        className="min-w-0 flex-1 rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <Button type="button" variant="outline" onClick={addPending} disabled={!pending.trim()}>Add</Button>
    </div>
    <p className="mt-2 text-xs text-muted-foreground">Press Enter or comma to add an item. Drag items or use their arrow controls to set priority order.</p>
    <Button type="button" variant="outline" className="mt-3" onClick={save}>Save {label.toLowerCase()}</Button>
  </fieldset>;
}
