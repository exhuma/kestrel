# Quickstart: Reliable Workflow Cleanup Validation

## Prerequisites

- A development database migrated to the current revision.
- Configured fixture, GitHub, and Jira source test doubles.
- A repository fixture with a disposable branch and workspace.

## Automated Validation

Run the focused backend tests while implementing:

```sh
cd backend
uv run pytest tests/test_workflow_cleanup.py tests/test_workflow_artifacts.py
```

Run the complete required quality gate before completion:

```sh
task quality
```

## End-to-End Scenario

1. Start a workflow that approves a PRD, posts comments, creates child tasks,
   pushes its branch, and opens a change request.
2. Open the workflow dashboard and confirm each generated resource appears in
   the artifact list.
3. Select Clean up workflow and confirm the action.
4. Verify the workspace, local branch, remote branch, PRD, child tasks, and
   recorded comments were removed or closed as documented in
   [the cleanup contract](contracts/workflow-cleanup.md).
5. Confirm the workflow no longer appears and that the next source poll starts
   a fresh run for the original task.
6. Repeat after manually deleting one artifact and confirm cleanup succeeds
   without an artifact-not-found error.
