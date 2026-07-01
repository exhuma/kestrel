export interface WorkflowStep {
  name: string
  session_id: string | null
  status: string
  deliverable: string | null
}

export interface WorkflowSummary {
  id: string
  repo: string
  issue_number: number
  status: string
}

export interface WorkflowDetail {
  id: string
  repo: string
  issue_number: number
  issue_title: string
  status: string
  branch: string
  steps: WorkflowStep[]
  current_session_id: string | null
  pr_url: string | null
  error: string | null
}
