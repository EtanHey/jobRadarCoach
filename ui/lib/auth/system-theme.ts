export interface SystemThemeTarget {
  classList: {
    toggle(name: string, force: boolean): unknown;
  };
}

export interface SystemThemeQuery {
  readonly matches: boolean;
  addEventListener(type: "change", listener: (event: { matches: boolean }) => void): void;
  removeEventListener(type: "change", listener: (event: { matches: boolean }) => void): void;
}

export function followSystemTheme(
  target: SystemThemeTarget,
  query: SystemThemeQuery,
): () => void {
  const apply = ({ matches }: { matches: boolean }) => {
    target.classList.toggle("dark", matches);
  };
  apply(query);
  query.addEventListener("change", apply);
  return () => query.removeEventListener("change", apply);
}
