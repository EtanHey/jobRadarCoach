type DetailSelection = Readonly<{ id: string | null; generation: number }>;
type DetailRead = Readonly<{ selection: DetailSelection; generation: number }>;

export function createDetailCoordinator() {
  let selection: DetailSelection = { id: null, generation: 0 };
  let readGeneration = 0;
  return {
    select(id: string | null) {
      selection = { id, generation: selection.generation + 1 };
      readGeneration += 1;
      return selection;
    },
    current() { return selection; },
    isCurrent(candidate: DetailSelection) {
      return candidate.id === selection.id && candidate.generation === selection.generation;
    },
    beginRead(): DetailRead { return { selection, generation: ++readGeneration }; },
    acceptRead(read: DetailRead) {
      return read.generation === readGeneration && read.selection.id === selection.id && read.selection.generation === selection.generation;
    },
    commitMutation(candidate: DetailSelection) {
      if (candidate.id !== selection.id || candidate.generation !== selection.generation) return false;
      readGeneration += 1;
      return true;
    },
  };
}

export function retainVisitCohort<T extends { id: string }>(current: T[] | null, incoming: T[]): T[] {
  if (current === null) return incoming;
  const incomingById = new Map(incoming.map((job) => [job.id, job]));
  const retainedIds = new Set(current.map((job) => job.id));
  return current.map((job) => incomingById.get(job.id) ?? job).concat(incoming.filter((job) => !retainedIds.has(job.id)));
}
