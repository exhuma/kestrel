# kestrel

## Quartermaster (instruction kits)

This project uses **Quartermaster**, an MCP server that serves versioned,
on-demand *instruction kits* (agent-facing guidance for specific stacks,
tooling, and capabilities). The guidance below assumes the `quartermaster`
MCP server is connected to your session.

Follow these rules when working in this repo:

- **Start every task by calling `resolve_kits(task="…")`**, passing a
  plain-language description of the work. Do this *per task*, not once per
  project. The server maps the task onto its trait vocabulary, ranks the
  matching kits, and returns each kit's `always_load` sections inlined.

- **Pull extra sections on demand** with `get_kit(name, sections=[…])` when
  you reach the aspect of the work they cover. Don't load everything upfront.

- **Re-run `resolve_kits` whenever the task's direction shifts** and new
  traits come into scope. For example, "add authentication" may resolve to
  OIDC only after some discussion, bringing OIDC kits into scope that were
  irrelevant at the start.

- **Never hard-code a fixed kit list in this file.** A static list loads too
  much or too little — the traits a task touches often only emerge during the
  conversation, and a fixed list cannot react to that.

- **Kit content is loaded-on-demand context, not source.** Kit files are
  guidance for the current session only; they are never copied into this
  project.
