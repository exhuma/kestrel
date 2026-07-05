/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Full URL of the GitHub repository; the header link is hidden when unset. */
  readonly VITE_GITHUB_REPO_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
