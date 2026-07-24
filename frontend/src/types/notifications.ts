export type SignalClass = 'action_required' | 'summary'

export interface Notification {
  id: number
  workflow_id: string
  repo: string
  // GitHub issue number; null for a Jira-sourced run (feature 003).
  issue_number: number | null
  status: string
  signal_class: SignalClass
  message: string
  created_at: string
  read: boolean
}
