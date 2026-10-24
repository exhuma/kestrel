# Feature Specification: A question with a closed set of answers is a choice

**Feature Branch**: `work`

**Created**: 2026-10-01

**Status**: Draft

**Input**: "Questions often come back with a plain text field while they
could be radio-/check-boxes. For example, I just saw this question with a
plain-text field: 'Will it need server-side storage or be ephemeral?' This
could have been a radio-group. […] The chosen widget should depend on the
question and potential options."

## Context

Feature 034 lets a question be open (free text) or a choice (one or
several of 2 to 8 options). Which it is, is decided only by the
interviewer that drafts it, guided by a single line ("prefer options
whenever you can"). Nothing checks that choice afterwards, so a question
that names its own alternatives can still reach the human as a text
field. Feature 038's question review already sees every new question
before any human does, but may only drop duplicates.

This feature extends 034 FR-002 and amends 038 FR-004.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Interviewers draft closed questions as choices (Priority: P1)

An interviewer asking "Will it need server-side storage or be ephemeral?"
gives it the options *Server-side storage* and *Ephemeral*. "What should
the export be called?" stays free text.

**Independent Test**: Read the instructions every interviewer receives
and confirm the rule and its examples are there.

**Acceptance Scenarios**:

1. **Given** the instructions an interviewer receives, **Then** they say
   a question MUST carry options when it names its own alternatives
   ("X or Y?"), can be answered yes or no, or picks from a known set, and
   MAY be free text only when its answer is genuinely open (a name, a
   number, a description, a reason).
2. **Given** those instructions, **Then** they show at least one
   single-choice, one multiple-choice and one open example.

### User Story 2 - The review turns a missed one into a choice (Priority: P1)

An interviewer still drafts "Will it need server-side storage or be
ephemeral?" as free text. Before the human sees it, the coordinator's
review gives it the two options. The human sees a radio group with
exactly the question the interviewer wrote.

**Independent Test**: Feed the review a reply that attaches options to an
open question; the opened gate shows that question as a choice with its
wording unchanged.

**Acceptance Scenarios**:

1. **Given** a kept, open new question, **When** the review gives it
   options, **Then** the question is asked as a choice with those options
   and its wording unchanged.
2. **Given** a review that gives options to a dropped question, a question
   that already has options, an unknown question, or that gives fewer
   than 2, more than 8, or repeated options, **Then** the whole review is
   ignored and every question is asked as drafted — none is lost.
3. **Given** a single interviewer's set with nothing asked before, **When**
   the set contains an open question, **Then** it is reviewed before its
   gate opens. **When** it contains only choices, **Then** its gate opens
   directly, as today.
4. **Given** a review that turned questions into choices, **Then** the
   record of the review lists them next to the dropped duplicates.

### Edge Cases

- The review returns no `options` list: behaviour is exactly as in 038.
- The review both drops and converts: drops apply first; a conversion of
  a dropped question makes the whole review invalid (scenario 2.2).
- The strategic-fit interview has no review step; it relies on the
  interviewer instructions (User Story 1) only.

## Requirements *(mandatory)*

- **FR-001**: Every interviewer's question-format instructions MUST state
  when a question must carry options and when it may be free text, with
  worked examples (single choice, multiple choice, open).
- **FR-002**: The question review MAY attach options (and whether several
  may be picked) to a kept, open new question. It MUST NOT change any
  question's wording. This amends 038 FR-004 ("only drop").
- **FR-003**: Attached options MUST meet 034 FR-001 (2 to 8 distinct,
  non-empty). Code MUST reject any invalid attachment by ignoring the
  whole review, never by losing or altering a question.
- **FR-004**: The review MUST run whenever a batch could hold a duplicate
  (as in 038) or holds an open new question. Its card is titled "Review
  the questions".
- **FR-005**: The review's record MUST list the questions it turned into
  choices.
- **FR-006**: The review's instructions MUST mark each new question as
  open or choice, so it knows which it may convert.

## Success Criteria *(mandatory)*

- **SC-001**: A question that names its own alternatives reaches the human
  as a choice, answered with one click.
- **SC-002**: No question's wording ever differs between what the
  interviewer drafted and what the human sees.
- **SC-003**: A malformed review never removes or changes a question.

## Assumptions

- The extra review in the single-set case costs one coordinator turn per
  round that has an open question; acceptable for a personal tool.
- No change to the frontend: it already renders choices from 034.
