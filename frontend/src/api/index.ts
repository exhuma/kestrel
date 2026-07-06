export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export interface TokenProvider {
  getToken(): string | null
}

let tokenProvider: TokenProvider = {
  getToken: () =>
    typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null,
}

export function setTokenProvider(p: TokenProvider): void {
  tokenProvider = p
}

let unauthorizedHandler: (() => void) | null = null

// Global 401 seam: bootstrap code registers a handler (e.g. redirect to
// login) that fires on any 401. Present even before auth exists.
export function setUnauthorizedHandler(fn: () => void): void {
  unauthorizedHandler = fn
}

export class ApiError extends Error {
  status: number
  data: unknown

  constructor(status: number, data: unknown) {
    super(`API error ${status}`)
    this.status = status
    this.data = data
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  const token = tokenProvider.getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!resp.ok) {
    if (resp.status === 401) unauthorizedHandler?.()
    throw new ApiError(resp.status, await resp.text())
  }
  return (await resp.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
