// Tree-shaken icon registry. Instead of shipping the whole Material Design
// Icons webfont (@mdi/font ≈ 400 kB woff2 + inflated CSS), we import only the
// glyphs the UI actually references from `@mdi/js` as SVG path strings. Vite
// tree-shakes the unused exports, so the production bundle carries just these
// paths (a few kB).
//
// Each entry is registered as a Vuetify icon alias and referenced in templates
// as `$name` (e.g. `<v-icon icon="$radar" />`). These are MERGED with
// Vuetify's own `mdi-svg` default aliases in `main.ts` — do not use this map
// alone as the alias set, or Vuetify's built-in component icons ($dropdown,
// $close, …) would stop resolving.
//
// When you add a new icon: import its `mdi*` export here, add an alias, and
// reference it as `$alias` in the template. The icons test guards that every
// `$alias` used in `src/` resolves to a non-empty path.
import {
  mdiAlertCircle,
  mdiArrowRight,
  mdiBell,
  mdiCircle,
  mdiCircleOutline,
  mdiClose,
  mdiCodeJson,
  mdiCogOutline,
  mdiRadar,
  mdiRocketLaunchOutline,
  mdiSubdirectoryArrowRight,
  mdiWeatherNight,
  mdiWeatherSunny,
} from '@mdi/js'

export const aliases: Record<string, string> = {
  alertCircle: mdiAlertCircle,
  arrowRight: mdiArrowRight,
  bell: mdiBell,
  circle: mdiCircle,
  circleOutline: mdiCircleOutline,
  close: mdiClose,
  codeJson: mdiCodeJson,
  cogOutline: mdiCogOutline,
  radar: mdiRadar,
  rocketLaunchOutline: mdiRocketLaunchOutline,
  subdirectoryArrowRight: mdiSubdirectoryArrowRight,
  weatherNight: mdiWeatherNight,
  weatherSunny: mdiWeatherSunny,
}
