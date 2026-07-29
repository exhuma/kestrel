"""Prompt templates and round-cap constants for the workflow pipeline."""
from __future__ import annotations

#: Base guard on the coordinator loop so a misbehaving agent can't spin
#: the interview forever. Retrying a failed specialist extends the cap
#: (one round per retry) up to ``MAX_REFINE_ROUNDS_HARD``.
MAX_REFINE_ROUNDS = 3
#: Absolute ceiling on interview rounds, retries included.
MAX_REFINE_ROUNDS_HARD = 6
#: How many times a failed specialist is retried before it becomes a
#: hard failure (a soft failure is retried on each answer submission).
MAX_SPECIALIST_RETRIES = 3

COORDINATOR_PROMPT = (
    "You are the refinement coordinator for a GitHub issue. Read the "
    "issue and the surrounding codebase, and consider the answers "
    "gathered so far. Decide which stakeholder profiles — if any — "
    "still need to be interviewed in the NEXT round.\n"
    "Prefer RESTRAINT: pick the FEWEST profiles whose perspective this "
    "issue genuinely needs. Every profile you add spends another agent "
    "session and asks the requester more questions, so never summon a "
    "specialist 'just in case'. For a small, unambiguous change it is "
    "correct to pick just requester/developer — or an empty set, if no "
    "clarification is needed at all. Summon a specialist ONLY when the "
    "issue clearly raises a decision in its domain; lean on each "
    "profile's when-to-summon signal in the roster below (for example: "
    "the architect only for larger, distributed, or structural work; "
    "the DBA only when the data model changes; infosec only for "
    "sensitive-data or auth; UX only for a user-facing surface).\n"
    "Choose from this roster (you may also name a new profile id if a "
    "needed stakeholder is genuinely missing):\n{roster}\n"
    "Return ONLY a JSON array of profile ids wrapped EXACTLY in "
    "<PROFILES> and </PROFILES> tags and nothing else, e.g. "
    '<PROFILES>["requester", "infosec"]</PROFILES>. Return an empty '
    "array <PROFILES>[]</PROFILES> once enough detail has been gathered "
    "and no further questions are needed. Do not edit any files.\n\n"
    "ISSUE:\n{issue}\n\n{answers}"
)
RECONCILE_PROMPT = (
    "Several stakeholder profiles were interviewed in PARALLEL about "
    "this GitHub issue and, unable to see each other's questions, "
    "proposed the pooled set below. Consolidate it into the FEWEST, "
    "SIMPLEST questions that still capture every decision the human "
    "must make.\n"
    "Below is the pool as JSON — each question with its \"id\", the "
    '"audience" profile that asked it, its "prompt", "why", "type", '
    '"required", "options", and "waiver_label" — followed by the '
    "roster describing each profile's remit.\n"
    "Rules:\n"
    "- FOLD every group of questions that turn on the SAME underlying "
    "fact into ONE question. Overlap counts EVEN WHEN the framings "
    "differ across domains: e.g. Product asking 'how should accounts "
    "be created?' and Eng asking 'is this open self-registration or a "
    "fixed/seeded set of users?' are the SAME decision — emit one "
    "question, not two.\n"
    "- Assign each resulting question to the SINGLE profile whose "
    "domain best owns it (set its \"audience\" to one of the input "
    "audiences), and keep only questions worth asking.\n"
    "- Phrase each question as simply as possible. Do NOT drop detail "
    "that changes the ANSWER, but drop redundant justification. Make "
    "requester/Product questions the PLAINEST and least technical of "
    "all.\n"
    "- Preserve a sensible \"type\" and, for select types, real "
    "\"options\"; carry over each kept question's waiver intent.\n"
    "- ACCOUNT FOR EVERY input question. In each consolidated "
    "question's \"folded_from\" list, put the \"id\" of every pooled "
    "question it represents — both the one you based it on and any you "
    "merged into it. Every input id MUST appear in exactly one "
    "\"folded_from\". This is how a real fold is told apart from an "
    "accidental drop; if an input's concern no longer matters, still "
    "fold its id into the closest surviving question rather than "
    "leaving it out.\n"
    "Output ONLY the consolidated questionnaire as a single JSON "
    "object wrapped EXACTLY in <QUESTIONS> and </QUESTIONS> tags and "
    "nothing else, matching this shape:\n"
    '{{"questions": [{{"id": "q1", "audience": "requester", '
    '"prompt": "...", "why": "...", "type": "single_select", '
    '"required": true, "waiver_label": "Unknown / N/A", '
    '"folded_from": ["requester:q1", "developer:q2"], '
    '"options": [{{"value": "a", "label": "Option A"}}]}}]}}\n'
    "Do not edit any files.\n\nISSUE:\n{issue}\n\n"
    "QUESTIONS:\n{questions}\n\nROSTER:\n{roster}"
)
CRITIC_PROMPT = (
    "You are a completeness critic reviewing a consolidated "
    "questionnaire for a GitHub issue. Several stakeholder profiles "
    "were interviewed, then a reconciler folded their questions into a "
    "smaller set. Your ONLY job is to catch a whole stakeholder's "
    "concern being LOST in that folding — not to judge wording or "
    "suggest new questions.\n"
    "For EACH audience in the list below, decide whether the decisions "
    "that audience needed to raise are still answerable from the FINAL "
    "questions — either asked directly or genuinely covered by a "
    "question now owned by another profile. Mark it covered=true when "
    "its concern survives (even if folded elsewhere), and covered=false "
    "ONLY when a real, decision-changing concern it raised is now "
    "missing.\n"
    "Return ONLY a JSON object wrapped EXACTLY in <COVERAGE> and "
    "</COVERAGE> tags and nothing else, matching this shape:\n"
    '{{"audiences": [{{"audience": "infosec", "covered": false, '
    '"missing": "no question about auth for the new endpoint"}}]}}\n'
    "Do not edit any files.\n\nISSUE:\n{issue}\n\n"
    "AUDIENCES:\n{audiences}\n\n"
    "ORIGINAL POOLED QUESTIONS:\n{pool}\n\n"
    "FINAL CONSOLIDATED QUESTIONS:\n{final}"
)
GENERATION_PROMPT = (
    "You are helping refine a GitHub issue before implementation by "
    "interviewing one stakeholder profile. {persona}\n\n"
    "Read the issue and the surrounding codebase. Ask ONLY the "
    "questions this profile needs answered that are not already covered "
    "by the answers gathered so far. Output a single JSON object "
    "wrapped EXACTLY in <QUESTIONS> and </QUESTIONS> tags and nothing "
    "else, matching this shape:\n"
    '{{"questions": [{{"id": "q1", "prompt": "...", "why": "...", '
    '"type": "single_select", "required": true, '
    '"waiver_label": "Unknown / N/A", '
    '"options": [{{"value": "a", "label": "Option A"}}]}}]}}\n'
    '"type" is one of "single_select", "multi_select", "boolean", '
    '"free_text" ("options" only applies to the select types). '
    '"waiver_label" is the label offered when the answerer cannot '
    "answer and must instead record a reason — tailor it to the "
    'question (for a security trade-off, e.g. "Accept this risk"). If '
    "this profile has nothing to ask, output "
    '<QUESTIONS>{{"questions": []}}</QUESTIONS>. Do not edit any '
    "files.\n\nISSUE:\n{issue}\n\n{answers}"
)
WRITE_REFINED_PROMPT = (
    "You have finished interviewing the stakeholders about this GitHub "
    "issue. Using the issue and all the answers below, write the "
    "complete refined issue description, folding the answers into a "
    "clear, implementation-ready specification. When the answers carry "
    "effort, timeline, dependency, or capacity signals (typically from "
    "the PM or engineering), add a dedicated '## Effort & timeline' "
    "section near the end of the issue with a rough estimate and the "
    "assumptions behind it; omit that section entirely when there is "
    "nothing to estimate. Output ONLY the refined "
    "issue wrapped EXACTLY in <REFINED_ISSUE> and </REFINED_ISSUE> tags "
    "and nothing else. Do not edit any files.\n\nISSUE:\n{issue}\n\n"
    "{answers}"
)
REFINE_FEEDBACK_PROMPT = (
    "The refined issue below was not approved. Revise it according to "
    "the feedback. Preserve any '## Assumptions & accepted risks' "
    "section unless the feedback changes it. Output ONLY the revised "
    "issue wrapped EXACTLY in <REFINED_ISSUE> and </REFINED_ISSUE> tags "
    "and nothing else.\n\nCURRENT REFINED ISSUE:\n{current}\n\n"
    "FEEDBACK:\n{feedback}"
)
#: Shared commit instruction for CODE_PROMPT/CODE_FEEDBACK_PROMPT (feature
#: 006): the coder and verifier share the same worktree, so there is no
#: need to serialize a diff to the verifier — the coder commits its own
#: work instead. kestrel places no special handling on the "WIP:" prefix
#: itself; every round still runs the full verify pass regardless of how
#: the coder phrased its commit message.
_COMMIT_INSTRUCTION = (
    "Commit your changes on this branch before you finish (`git add -A "
    "&& git commit`): use a real, descriptive commit message when you are "
    "confident in the result, or a `WIP: ...`-prefixed message naming your "
    "specific uncertainty when you are not and expect the verifier may "
    "reject this round."
)
CODE_FEEDBACK_PROMPT = (
    "The verifier did not accept the implementation — this means the PRD/"
    "design was not met or the evidence showed a real failure; the "
    "feedback below may also carry incidental quality notes, but those are "
    "not why this was rejected. Fix what actually failed first. Address "
    "this feedback by editing the repository now. " + _COMMIT_INSTRUCTION +
    " Then stop."
    "\n\nFEEDBACK:\n{feedback}\n\nDESIGN:\n{design}"
)
DESIGN_PROMPT = (
    "Read this approved PRD and the codebase, then produce a concise "
    "high-level design and implementation plan. Do not use the ExitPlanMode "
    "tool and do not write the plan to a file — this session is headless. "
    "Output the complete plan directly in your final response, wrapped "
    "EXACTLY in <PLAN> and </PLAN> tags. Then, on a new line, classify this "
    "project's user-facing boundary — the surface a later verification step "
    "will need to launch and exercise for real — wrapped EXACTLY in "
    "<BOUNDARY> and </BOUNDARY> tags, containing ONLY one of: http (the "
    "project exposes an HTTP API, e.g. FastAPI/Flask/Express), ui (the "
    "project exposes a web UI, e.g. a Vite/React/Vue app with a dev or "
    "preview server), both (it exposes both), or none (neither, e.g. a "
    "library or CLI tool). Output nothing else. Do not edit any "
    "files.\n\nPRD:\n{issue}"
)
CODE_PROMPT = (
    "Implement the design below. Make all necessary code edits in this "
    "repository now. This runs autonomously — there is no human to ask, so "
    "make the best decision you can and implement it. Practice test-first "
    "development: write the tests for the behaviour you are adding (or a "
    "failing test reproducing a bug you are fixing) before or alongside the "
    "implementation, matching the project's existing test conventions and "
    "a sensible testing pyramid (favour fast unit/integration tests; keep "
    "end-to-end coverage minimal). Verification later in this pipeline "
    "checks live, observed behaviour — it is not a substitute for durable, "
    "repo-committed tests, which are your responsibility. Once the "
    "implementation is complete, " + _COMMIT_INSTRUCTION + " Then just "
    "stop — do not wrap your final summary in any tags."
    "\n\nPRD:\n{prd}\n\nDESIGN:\n{design}"
)
#: permission_mode for the explore turn (feature 005, US1): the explore
#: turn needs Bash/MCP tool execution approved without an interactive
#: prompt, since every kestrel session runs headless (no TTY to answer
#: one). "bypassPermissions" is the broadest unattended-execution mode the
#: claude CLI offers — chosen over "acceptEdits" (whose documented scope is
#: file-edit auto-approval, not general tool execution) per research.md R2.
#: This is a best-effort default, not empirically verified against a real
#: `claude` CLI session (unavailable in this environment); confirm it
#: against a live operator login before relying on it, and swap it here if
#: it proves insufficient.
EXPLORE_PERMISSION_MODE = "bypassPermissions"

EXPLORE_PROMPT = (
    "You are verifying an implementation by observing the running, "
    "modified project — not by reading its code. This project's "
    "user-facing boundary is: {boundary}. Using whatever tools you have "
    "available (a shell, browser automation, etc.), launch the project in "
    "this worktree and exercise it for real:\n"
    "- If the boundary is http or both: start the modified application and "
    "issue real HTTP requests against it that exercise what the PRD "
    "describes.\n"
    "- If the boundary is ui or both: start the project's dev/preview "
    "server and drive it via browser automation, visually inspecting the "
    "result.\n"
    "- If the boundary is ui or both AND you drove the UI, save PNG "
    "screenshots of the key states you exercised into the worktree "
    "directory `{screenshots_dir}` (create it if needed; name them like "
    "`dashboard-01.png`). These are shown to the human reviewer and "
    "attached to the ticket, so capture what best evidences the result.\n"
    "If a tool you need for this boundary (e.g. a browser-automation tool) "
    "is not available to you, say so EXPLICITLY and unambiguously in your "
    "response — verification is degraded/incomplete in that case, and "
    "that must be clear, not silently indistinguishable from a normal "
    "pass. Stop any process you started before you finish. Describe what "
    "you did and observed in your final response; there is no required "
    "format for this turn.\n\nPRD:\n{prd}\n\nDESIGN:\n{design}"
)
VERIFY_PROMPT = (
    "You are the verifier. Judge whether the implementation satisfies the PRD "
    "and design, the way an end user or stakeholder would judge the result — "
    "not a code reviewer. Weigh what you just observed by exploring the "
    "running application (in the turn immediately before this one, if you "
    "explored anything) as the primary basis of your verdict — a failing "
    "observation is a rejection. Where you did not explore anything, judge "
    "based on the PRD and design alone — you are not shown a diff and do not "
    "need one; the codebase in this worktree is the implementation. "
    "accept/reject is decided SOLELY by whether the implementation meets "
    "the PRD/design and what you observed — never by code quality, "
    "maintainability, or documentation on their own. If you notice a code "
    "quality or documentation concern, note it in feedback as an aside, but "
    "it MUST NOT by itself set accept=false when the requirement is "
    "otherwise met and nothing you observed failed. Respond "
    "with ONLY a JSON object wrapped EXACTLY in <VERDICT> and </VERDICT> "
    "tags, matching this shape:\n"
    '{{"accept": true, "feedback": "...", "observations": '
    '[{{"name": "...", "kind": "http", "passed": true, "detail": "..."}}]}}\n'
    '"observations" is OPTIONAL — include one entry per distinct thing you '
    "exercised while exploring the running application (kind is \"http\" or "
    '"ui"), each with a bounded, factual "detail". Omit it entirely when '
    "you did not explore anything this round.\n"
    "This session is headless: do not use the ExitPlanMode tool and do not "
    "stop to investigate with tools — output the verdict JSON directly in "
    "your final response and nothing else. "
    "Set accept=false and give specific, actionable feedback for the coder "
    "when the implementation is inconsistent or what you observed shows "
    "failures.\n\nPRD:\n{prd}\n\nDESIGN:\n{design}"
)
#: Optional refine-stage turn: mock up the PRD's screens as static HTML/CSS
#: and screenshot them, so the human sees the proposed UI at the approval
#: gate. Gated on a FILE_EDITS+TOOL_USE-capable refine backend; degrades
#: (self-reports) when no browser tool is available (see driver/mockups.py).
MOCKUP_PROMPT = (
    "You are producing quick visual mockups for a change still being "
    "refined, so a human reviewer can see the proposed UI before "
    "approving the PRD below. Using static HTML and CSS only (no backend, "
    "no framework build), mock up the key screens or states the PRD "
    "describes. Then, using your browser-automation tool, open each mockup "
    "and save a PNG screenshot into the worktree directory "
    "`{screenshots_dir}` (create it if needed; name them like "
    "`login-01.png`). Keep the mockups lightweight and throwaway — they "
    "illustrate intent, they are not the implementation. If you have no "
    "browser-automation tool available, say so EXPLICITLY and do not "
    "fabricate screenshots. Describe what you produced in your final "
    "response; there is no required format for this turn.\n\nPRD:\n{prd}"
)
