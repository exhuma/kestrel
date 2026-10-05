# Next steps

The backlog lives in the
[GitHub issue tracker](https://github.com/exhuma/kestrel/issues); this page
only points at where the open work is grouped.

## Exploration epics

- [#75](https://github.com/exhuma/kestrel/issues/75) — integrations
  (more task sources, code hosts and notifiers).
- [#76](https://github.com/exhuma/kestrel/issues/76) — operations
  (deployment, backup, upgrades).
- [#77](https://github.com/exhuma/kestrel/issues/77) — observability
  (metrics, traces; see also [`qm-alignment.md`](qm-alignment.md)).
- [#78](https://github.com/exhuma/kestrel/issues/78) — impact investigation.
- [#81](https://github.com/exhuma/kestrel/issues/81) — access and identity:
  today everyone an authenticating proxy lets through can do everything.

## Follow-up of the Jira ticket conversation (feature 046)

Open items after the first Jira alpha are tracked in GitHub
[#80](https://github.com/exhuma/kestrel/issues/80). The walk-through that
validates the feature is `specs/046-jira-first-alpha/quickstart.md`.

## Out of scope by design

- **Multi-user authorisation.** Kestrel is single-user. A reverse proxy can
  authenticate people (see [Deploying on Kubernetes](deploy-kubernetes.md)),
  but kestrel itself does not tell them apart (#81).
- **Auto-merging.** Kestrel opens a change request; merging stays a human act.
- **Moving an ingested ticket.** Kestrel never changes the status of a ticket
  it ingested (constitution, access model).
