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

export function uniqueJobsById<T extends { id: string }>(jobs: T[]): T[] {
  const indexes = new Map<string, number>();
  const unique: T[] = [];
  for (const job of jobs) {
    const index = indexes.get(job.id);
    if (index === undefined) {
      indexes.set(job.id, unique.length);
      unique.push(job);
    } else {
      unique[index] = job;
    }
  }
  return unique.length === jobs.length ? jobs : unique;
}

export function retainVisitCohort<T extends { id: string }>(current: T[] | null, incoming: T[]): T[] {
  const uniqueIncoming = uniqueJobsById(incoming);
  if (current === null) return uniqueIncoming;
  const uniqueCurrent = uniqueJobsById(current);
  const incomingById = new Map(uniqueIncoming.map((job) => [job.id, job]));
  const retainedIds = new Set(uniqueCurrent.map((job) => job.id));
  return uniqueCurrent
    .map((job) => incomingById.get(job.id) ?? job)
    .concat(uniqueIncoming.filter((job) => !retainedIds.has(job.id)));
}
