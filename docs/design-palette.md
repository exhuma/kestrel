# Design palette

kestrel uses Vuetify's built-in `light` and `dark` themes. The only colours
it adds are one semantic colour per specialist. Everything is configured in
`frontend/src/plugins/vuetify.ts`, which `main.ts` and the component tests
both use.

## Rules

- **No colour literals in components.** Use a theme colour: a Vuetify
  `color` prop (`color="warning"`), a class (`text-error`), or the CSS
  variable `rgb(var(--v-theme-<name>))`.
- **Colour is never the only signal.** Anything coloured also says what it
  means in words or with an icon. For example, the phase spine pairs each
  status with an icon and a word (feature 034).
- **Readable in both themes.** A colour you add needs a light-theme value
  dark enough to read on white, and a dark-theme value light enough to read
  on the dark surface.

## Specialist colours (feature 039)

Each built-in specialist has a theme colour `specialist-<id>`. The palette
is `frontend/src/lib/specialistColor.ts`:

| Specialist | Light | Dark |
| --- | --- | --- |
| requester (Product Owner) | `#B45309` | `#FCD34D` |
| pm | `#1D4ED8` | `#93C5FD` |
| uiux | `#BE185D` | `#F9A8D4` |
| developer | `#047857` | `#6EE7B7` |
| infosec | `#B91C1C` | `#FCA5A5` |
| dba | `#6D28D9` | `#C4B5FD` |
| architect | `#0E7490` | `#67E8F9` |
| ops | `#4D7C0F` | `#BEF264` |
| qa | `#C2410C` | `#FDBA74` |
| coordinator | `#334155` | `#CBD5E1` |
| coder | `#0F766E` | `#5EEAD4` |
| verifier | `#4338CA` | `#A5B4FC` |
| input-security | `#A16207` | `#FDE047` |

Use `specialistColor(id)` to get the theme colour name. It returns `null`
for a specialist an operator added, which is then shown neutrally.

The interview uses these colours as a faint tint (6%) with a thin border on
each profile's questionnaire, next to the profile's name.

To add a specialist colour, add its id to `SPECIALIST_PALETTE` with a light
and a dark value. The theme picks it up automatically.
