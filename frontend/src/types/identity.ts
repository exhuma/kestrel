/** The authenticated identity, as forwarded by oauth2-proxy. */
export interface Identity {
  username: string | null
  email: string | null
  preferred_username: string | null
}
