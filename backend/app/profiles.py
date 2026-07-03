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
    "requester": Profile(
        id="requester",
        label="Requester",
        badge="user",
        description=(
            "The stakeholder who filed the change: owns the intent, "
            "business value, scope, and acceptance criteria."
        ),
        system_prompt=(
            "You are interviewing the REQUESTER (the business "
            "stakeholder who asked for this change). Ask only what "
            "clarifies intent, scope, priority, acceptance criteria, "
            "and user-facing behaviour. Avoid implementation detail — "
            "that is the developer's concern."
        ),
    ),
    "developer": Profile(
        id="developer",
        label="Developer",
        badge="agent",
        description=(
            "The engineer who will implement the change: owns "
            "technical approach, feasibility, and effort."
        ),
        system_prompt=(
            "You are interviewing the DEVELOPER who will implement "
            "this change. Ask only what resolves technical ambiguity: "
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
