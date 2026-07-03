"""Stakeholder profiles for the refinement interview.

A *profile* is an audience the refinement questions are aimed at —
the requester who filed the change, the developer who will build it,
or a specialist reviewer (infosec, and later sysadmin, observability,
cyber). Each profile carries a persona/expertise fragment that is
prepended to the question-generation prompt so the questions asked of
that audience are shaped by its expertise.

The roster is seeded here (static, versioned config) but the
coordinator agent may name a profile outside it; unknown ids resolve
to a generic profile via :func:`get_profile` so the system never
breaks on an agent-minted audience.

Profiles are a *visible* concept and a prompt-routing mechanism only:
the service stays single-user and profiles carry no access control.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Fallback badge tone for agent-minted profiles not in the roster.
_DEFAULT_BADGE = "sys"


@dataclass(frozen=True)
class Profile:
    """One stakeholder audience for refinement questions.

    :param id: Stable machine id, e.g. ``"infosec"``.
    :param label: Human-readable name shown in the UI.
    :param badge: Theme tone token for the UI badge (see
        ``frontend/src/styles/theme.css``): one of ``user``,
        ``agent``, ``warn``, ``ok``, ``err``, ``sys``.
    :param description: One-line role summary given to the
        coordinator so it can decide relevance.
    :param system_prompt: Persona/expertise fragment prepended to
        the generation prompt when asking this audience's questions.
    """

    id: str
    label: str
    badge: str
    description: str
    system_prompt: str


#: Seeded roster. Extra specialists are one entry each.
ROSTER: dict[str, Profile] = {
    # The machine ids ("requester"/"developer") stay stable so the
    # coordinator's routing and every namespaced question id keep
    # working; only the human-facing labels change.
    "requester": Profile(
        id="requester",
        label="Product",
        badge="user",
        description=(
            "The stakeholder who filed the change: owns the intent, "
            "business value, scope, and acceptance criteria."
        ),
        system_prompt=(
            "You are interviewing PRODUCT (the business stakeholder "
            "who asked for this change). Ask only what clarifies "
            "intent, scope, priority, acceptance criteria, and "
            "user-facing behaviour. Avoid implementation detail — "
            "that is Engineering's concern. Phrase every question in "
            "the plainest, least technical language possible: a "
            "non-technical stakeholder must be able to answer it."
        ),
    ),
    "developer": Profile(
        id="developer",
        label="Eng",
        badge="agent",
        description=(
            "The engineer who will implement the change: owns "
            "technical approach, feasibility, and effort."
        ),
        system_prompt=(
            "You are interviewing ENGINEERING, who will implement this "
            "change. Ask only what resolves technical ambiguity: "
            "approach, affected components, data model, dependencies, "
            "edge cases, and testability. Read the surrounding "
            "codebase to ground your questions."
        ),
    ),
    "infosec": Profile(
        id="infosec",
        label="InfoSec",
        badge="warn",
        description=(
            "Security reviewer: owns authn/authz, data protection, "
            "attack surface, and risk sign-off."
        ),
        system_prompt=(
            "You are interviewing INFOSEC. Ask only what surfaces "
            "security-relevant decisions: authentication, "
            "authorization, sensitive-data handling, attack surface, "
            "auditing, and compliance. Where a decision carries "
            "residual risk, frame the question so it can be answered "
            "either with a control or with an explicit, reasoned risk "
            "acceptance."
        ),
    ),
    "uiux": Profile(
        id="uiux",
        label="UX",
        badge="ok",
        description=(
            "Design & usability: user flows, information architecture, "
            "empty/loading/error states, responsive and accessible "
            "behaviour, and copy. Summon when the change has a "
            "user-facing surface."
        ),
        system_prompt=(
            "You are interviewing UX (design and usability). Ask only "
            "what clarifies user flows and journeys, information "
            "architecture, empty/loading/error states, responsive and "
            "mobile behaviour, accessibility (keyboard, screen-reader, "
            "contrast), and user-facing copy. Avoid backend or "
            "infrastructure detail."
        ),
    ),
    "dba": Profile(
        id="dba",
        label="DBA",
        badge="sys",
        description=(
            "Database specialist: data model, schema changes and "
            "migrations, indexing and query performance, data "
            "volume/retention, and integrity constraints. Summon when "
            "the change touches the data model or schema."
        ),
        system_prompt=(
            "You are interviewing the DBA. Ask only what clarifies the "
            "data model, schema changes and migrations, indexing and "
            "query performance, expected data volume and retention, and "
            "integrity/consistency constraints. Avoid UI detail; defer "
            "broad architecture to the architect."
        ),
    ),
    "pm": Profile(
        id="pm",
        label="PM",
        badge="user",
        description=(
            "Project manager: scope boundaries, priority, dependencies, "
            "sequencing, deadlines, team capacity, and delivery risk — "
            "the inputs needed to estimate effort and timeline. Summon "
            "when timeline or effort matters."
        ),
        system_prompt=(
            "You are interviewing the PROJECT MANAGER. Ask only what "
            "clarifies scope boundaries, priority, dependencies and "
            "sequencing, deadlines and constraints, available capacity, "
            "and delivery risks — the inputs needed to estimate effort "
            "and timeline. Do not ask about implementation detail."
        ),
    ),
    "qa": Profile(
        id="qa",
        label="QA",
        badge="err",
        description=(
            "Quality assurance: test strategy, acceptance criteria, "
            "edge and negative paths, test data/environments, and "
            "regression risk. Summon when correctness or acceptance is "
            "non-trivial."
        ),
        system_prompt=(
            "You are interviewing QA. Ask only what clarifies test "
            "strategy, acceptance criteria, edge cases and negative "
            "paths, the data and environments needed to test, and "
            "regression risk. Frame questions so the definition of done "
            "becomes testable."
        ),
    ),
    "architect": Profile(
        id="architect",
        label="Arch",
        badge="agent",
        description=(
            "Architect (system and data): service/module boundaries, "
            "integration and contracts, data flow and ownership, "
            "scalability, and consistency trade-offs. Summon only for "
            "larger, distributed, or structurally cross-cutting changes."
        ),
        system_prompt=(
            "You are interviewing the ARCHITECT, responsible for system "
            "and data architecture. Ask only what clarifies structural "
            "decisions: service/module boundaries, integration points "
            "and contracts, data flow and ownership across components, "
            "scalability, and consistency/availability trade-offs. Defer "
            "tactical schema detail to the DBA and implementation detail "
            "to Engineering. Only raise questions that matter for larger "
            "or distributed designs."
        ),
    ),
    "ops": Profile(
        id="ops",
        label="Ops",
        badge="warn",
        description=(
            "Operations/SRE: deployment and rollout, configuration and "
            "secrets, observability (metrics/logs/alerts), scaling and "
            "capacity, availability/SLOs, backups and disaster "
            "recovery, and runbooks. Summon when the change affects how "
            "the system or platform is deployed, run, or monitored."
        ),
        system_prompt=(
            "You are interviewing OPS (who deploys, runs, and operates "
            "this system and its platform). Ask only what clarifies "
            "deployment and rollout strategy, configuration and secret "
            "handling, observability (metrics, logs, alerts), scaling "
            "and capacity, availability and SLOs, backups and disaster "
            "recovery, and operational runbooks. Avoid product and UI "
            "detail."
        ),
    ),
}


def get_profile(profile_id: str) -> Profile:
    """
    Return the roster profile for *profile_id*, or a generic one.

    Agent-minted ids outside the seeded roster resolve to a generic
    profile (titled from the id) so downstream code — badges,
    grouping, persona prompt — always has a value to use.

    :param profile_id: The audience id to look up.
    :returns: The matching :class:`Profile`, or a generic fallback.
    """
    known = ROSTER.get(profile_id)
    if known is not None:
        return known
    label = profile_id.replace("_", " ").replace("-", " ").title()
    return Profile(
        id=profile_id,
        label=label,
        badge=_DEFAULT_BADGE,
        description=f"Stakeholder profile '{label}'.",
        system_prompt=(
            f"You are interviewing the {label} stakeholder. Ask only "
            "questions that fall within that role's expertise and "
            "responsibility for this change."
        ),
    )


def roster_summary() -> str:
    """
    Render the seeded roster as ``- id: description`` lines.

    Given to the coordinator so it can pick relevant profiles by id.
    """
    return "\n".join(
        f"- {p.id}: {p.description}" for p in ROSTER.values()
    )
