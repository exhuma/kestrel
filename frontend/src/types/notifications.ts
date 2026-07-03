export interface Notification {
  id: number
  workflow_id: string
  repo: string
  issue_number: number
  status: string
  message: string
  created_at: string
  read: boolean
}
