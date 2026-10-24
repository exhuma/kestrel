# Feature Specification: Work whose result cannot be read is tried again

**Feature Branch**: `work`

**Created**: 2026-09-30

**Status**: Implemented (2026-09-30)

**Input**: In the operator's run, a decomposition card returned malformed JSON. The board showed "Unparseable decomposition proposal on card card-619f1091: malformed result: Expecting ',' delimiter …" and nobody could recover or retry.

## Context

A card's result is accepted before it is parsed. When it cannot be read, the card is already `done`, so nothing is left to act on:
- The operator's Retry applies only to `failed` cards.
- The escalation (`coordinator_review`) gave the coordinator no way to run the work again or close the escalation.

Every structured result is affected: the understanding restatement, strategic interview, interview plan, interview questions, PRD, decomposition and estimates.

## Decisions

- **Automatic first, the operator second.** An unreadable result makes the same work run again as a fresh card of the same kind. The new card has the same roles, permission, task and dependencies, and records the attempt it replaces (`source_card_id`). Its prompt says why the previous attempt could not be used. This happens up to `board_unreadable_retry_cap` times (default 1; 0 escalates at once).
- **Then escalated, with Retry.** Once the automatic attempts are used up, the result is escalated as before, with the last attempt as its source. The escalation offers the operator **Retry**: the work runs again as a fresh card, and the escalation is closed (done).
- **A replaced attempt is not an attempt of its own.** Interview rounds and understanding drafts are counted without it.
- **Only unreadable results are retried.** Results that can be read but are not acceptable still escalate as before, for example an interview plan that names no one, or estimates that arrive while CAB-2 waits.

## User Scenarios & Testing *(mandatory)*

1. **Given** a specialist returns malformed output, **When** its result is routed, **Then** the same work is queued again. The new attempt is told what was wrong, and no escalation appears.
2. **Given** the retry is also unreadable, **When** its result is routed, **Then** an escalation appears for the coordinator and the operator.
3. **Given** that escalation, **When** the operator clicks Retry, **Then** the work runs again as a fresh card and the escalation is closed.
4. **Given** an interview card retried after unreadable output, **When** rounds are counted, **Then** the retry does not use up a round.

## Functional Requirements

- **FR-001**: Result routes report an unreadable result (`UnreadableResultError`) instead of escalating it themselves. Dispatch decides whether to retry or escalate.
- **FR-002**: An automatic retry records `card.unreadable_retry` with the reason and wakes dispatch. An operator retry records `intervention.retry`.
- **FR-003**: `allowed_actions` offers `retry` on an open escalation that has a source card. Retrying requires the source card to be finished.
- **FR-004**: `board_unreadable_retry_cap` (default 1, at least 0) bounds the automatic attempts per piece of work.

## Assumptions

- An escalation created before feature 041 has no source card, so it offers no Retry. Such cards can still be cancelled.
- Verifier results keep their own routing (feature 031 rounds). An unreadable one escalates, and can then be retried from the escalation.
