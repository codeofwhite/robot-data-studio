export type EngineId = 'genesis' | 'isaac_sim';

export function engineLabel(engine: EngineId | string | null | undefined): string {
  if (engine === 'isaac_sim') return 'Isaac Sim';
  if (engine === 'genesis' || engine === 'clothtwin') return 'Genesis';
  return engine || 'Unknown';
}
