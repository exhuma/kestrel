# Mission Control design palette

Source of truth: `frontend/src/styles/theme.css`. Components reference these
CSS custom properties and introduce no new color literals of their own.

## Surfaces (layered navy "ink", each step lighter)

| Token | Hex | Use |
|---|---|---|
| `--ink-900` | `#0B1220` | app background |
| `--ink-850` | `#0E1626` | header / recessed |
| `--ink-800` | `#111A2B` | dispatch rail |
| `--ink-750` | `#14203A` | input wells |
| `--ink-700` | `#16213A` | cards / stage surface |
| `--ink-650` | `#1B2942` | hover |
| `--line` | `#223049` | hairline borders |
| `--line-soft` | `#1A2438` | softer dividers |

## Text

| Token | Hex |
|---|---|
| `--text-hi` | `#E6EDF7` |
| `--text-mid` | `#9FB0C7` |
| `--text-dim` | `#62748C` |

## Signal + status

| Token | Hex | Meaning |
|---|---|---|
| `--signal` / `--run` | `#35E6C9` | primary action, live/running (mint-teal) |
| `--signal-ink` | `#04231F` | text on signal-color fills |
| `--idle` | `#7C8CA5` | idle status |
| `--ok` | `#5BD98A` | success |
| `--warn` | `#F5B14C` | tool activity / warning |
| `--err` | `#F2727F` | error |
| `--user` | `#6EA8FF` | user-authored events |

## Other literals (not tokens)

- `#4FF0D6` — hover shade for the primary button (`.btn--primary:hover`).
- `rgba(53, 230, 201, 0.16)` (`--signal-glow`) — focus-ring / glow, derived
  from `--signal`.

Everything else in `theme.css` is either a `var(--token)` reference or plain
grayscale (`transparent`, black in shadows). No other hex/rgb literals are
used.

## Type

| Token | Value |
|---|---|
| `--font-sans` | `'IBM Plex Sans', system-ui, -apple-system, sans-serif` |
| `--font-mono` | `'IBM Plex Mono', ui-monospace, 'SFMono-Regular', monospace` |
