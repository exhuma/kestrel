# Feature Specification: A colour per specialist

**Feature Branch**: `work`

**Created**: 2026-09-30

**Status**: Implemented (2026-09-30)

**Input**: Review of Vikunja 710 (2026-09-30). Now that several profiles are
interviewed (feature 038), their questionnaires should be easy to tell
apart. The developer asked for a unique semantic theme colour per kestrel
specialist, used as a very faint tint behind each questionnaire. The colours
come from a theme palette.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Tell the questionnaires apart (Priority: P1)

On the interview page, each profile's questionnaire has a faint tint and a
thin border in its specialist's colour, and is headed by the profile's name
("Design & Usability", not "uiux").

**Acceptance Scenarios**:

1. **Given** an interview with two profiles, **When** it is shown, **Then**
   each questionnaire is tinted in its own specialist's colour, in both the
   light and the dark theme.
2. **Given** a specialist an operator added, **When** its questionnaire is
   shown, **Then** it is neutral, with no tint.
3. **Given** any questionnaire, **When** it is shown, **Then** its heading
   names the profile, so the colour is never the only signal.

## Requirements *(mandatory)*

- **FR-001**: Every built-in specialist MUST have a semantic theme colour
  `specialist-<id>`, with a light and a dark value, all different.
- **FR-002**: The theme configuration MUST be shared by the app and the
  component tests.
- **FR-003**: No component may use a colour literal for a specialist.

## Success Criteria *(mandatory)*

- **SC-001**: Two questionnaires on one page never share a tint, unless
  one of them belongs to an operator-added specialist.
