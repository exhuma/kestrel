// ESLint flat config — STRUCTURAL guardrails only (see AGENTS.md "Code-quality
// guardrails"). Prettier owns formatting; this config deliberately enables only
// the size/complexity limits plus two SonarJS structural checks, and no
// recommended rule sets, so it stays focused on structural drift.
//
// These thresholds are HARD LIMITS. When one is hit, split the module or extract
// a function/composable — do NOT raise the threshold or add eslint-disable.
import tseslint from 'typescript-eslint'
import vueParser from 'vue-eslint-parser'
import sonarjs from 'eslint-plugin-sonarjs'
import globals from 'globals'

const structuralRules = {
  complexity: ['error', 10],
  'max-lines': ['error', { max: 500, skipBlankLines: true, skipComments: true }],
  'max-lines-per-function': [
    'error',
    { max: 60, skipBlankLines: true, skipComments: true },
  ],
  'max-params': ['error', 5],
  'max-depth': ['error', 4],
  'max-nested-callbacks': ['error', 3],
  'sonarjs/cognitive-complexity': ['error', 15],
  'sonarjs/no-identical-functions': 'error',
}

export default [
  {
    ignores: ['dist/**', 'coverage/**', 'node_modules/**'],
  },
  {
    files: ['**/*.{js,mjs,cjs,ts,mts,cts}'],
    languageOptions: {
      parser: tseslint.parser,
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: { sonarjs },
    rules: structuralRules,
  },
  {
    // Vue SFCs: vue-eslint-parser handles the SFC, delegating <script> to the
    // TypeScript parser so the structural rules analyse the script block.
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
      globals: { ...globals.browser },
    },
    plugins: { sonarjs },
    rules: structuralRules,
  },

  // --- Grandfathered structural violations present when the harness was
  // introduced. TODO(quality): refactor and delete each entry as the code is
  // split up. This is a shrinking debt list, NOT a template — do not add new
  // entries or disable rules to make a check pass. New files get no exemptions.
  {
    files: ['src/components/SessionPanel.vue'],
    rules: { complexity: 'off', 'sonarjs/cognitive-complexity': 'off' },
  },
  {
    files: ['src/components/WorkflowPanel.vue'],
    rules: { 'max-lines': 'off' },
  },
  {
    files: ['src/composables/useSessions.ts', 'src/composables/useWorkflows.ts'],
    rules: { 'max-lines-per-function': 'off' },
  },
  {
    files: ['src/lib/eventView.ts', 'src/lib/questionnaire.ts'],
    rules: { complexity: 'off' },
  },
  {
    files: [
      'tests/components/QuestionnaireForm.test.ts',
      'tests/composables/useWorkflows.test.ts',
      'tests/lib/eventView.test.ts',
    ],
    rules: { 'max-lines-per-function': 'off' },
  },
]
