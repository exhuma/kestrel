# Fixture folder contract

The fixture root contains task folders recursively. A task folder is discovered
only when it contains `task.json`; its identity is `fixture:` plus its
root-relative POSIX path.

`task.json` requires `title`, `body`, and an absolute bare-repository
`code_repo`. Optional `base_branch` overrides the repository's symbolic `HEAD`.

Human feedback is UTF-8 Markdown in `comments/` named
`YYYY-MM-DDTHH.MM.SS[-N].md`. Kestrel replies use the same timestamp with
`-kestrel[-N].md` and are excluded solely by that filename marker.

Attachments are written below `attachments/`. Generated child tasks are written
below `children/`, each with their own `task.json`. No reference or generated
path may escape the configured fixture root or owning task directory.
