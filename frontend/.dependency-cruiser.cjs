// dependency-cruiser contracts for the frontend. Encodes the real layering
// (components -> composables -> api; lib & types are shared leaves) and, at
// minimum, forbids import cycles. Do not weaken these to make an import pass —
// restructure the code (see AGENTS.md "Code-quality guardrails").
/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: 'no-circular',
      severity: 'error',
      comment: 'No import cycles anywhere in the frontend module graph.',
      from: {},
      to: { circular: true },
    },
    {
      name: 'api-is-a-leaf',
      severity: 'error',
      comment:
        'The HTTP client (src/api) is the bottom layer; it must not import ' +
        'components or composables.',
      from: { path: '^src/api' },
      to: { path: '^src/(components|composables)' },
    },
    {
      name: 'shared-leaves-do-not-import-up',
      severity: 'error',
      comment:
        'Shared leaves (src/lib, src/types) must not import components, ' +
        'composables, or the api client.',
      from: { path: '^src/(lib|types)' },
      to: { path: '^src/(components|composables|api)' },
    },
    {
      name: 'no-orphans',
      severity: 'ignore',
      from: {},
      to: {},
    },
  ],
  options: {
    doNotFollow: { path: 'node_modules' },
    exclude: { path: '(node_modules|dist|tests)' },
    tsConfig: { fileName: 'tsconfig.app.json' },
    enhancedResolveOptions: {
      extensions: ['.ts', '.js', '.mjs', '.vue', '.json'],
    },
  },
}
