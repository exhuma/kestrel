import { ref } from 'vue'
import { api } from '../api'
import type { Screenshot } from '../types/workflows'

/**
 * Per-instance fetch state for one run's screenshots. Not a singleton:
 * each gallery owns its own list so two stages can render independently.
 */
export function useScreenshots() {
  const shots = ref<Screenshot[]>([])

  // Best-effort: a run with no screenshots (or a not-yet-provisioned one)
  // simply yields an empty gallery rather than an error banner.
  async function load(workflowId: string): Promise<void> {
    try {
      shots.value = await api.get<Screenshot[]>(
        `/api/workflows/${workflowId}/screenshots`,
      )
    } catch {
      shots.value = []
    }
  }

  return { shots, load }
}
