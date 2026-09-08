export type HealthState = 'unknown' | 'healthy' | 'unhealthy'

export interface SourceHealth {
  name: string
  state: HealthState
  checked_at: string | null
}
