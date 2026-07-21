export type SignalClass = 'action_required' | 'summary'

export interface Notification {
  id: number
  workflow_id: string
  repo: string
  issue_number: number
  status: string
  signal_class: SignalClass
  message: string
  created_at: string
  read: boolean
}
