export const API_BASE =
  import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export interface TokenProvider {
  getToken(): string | null
}

let tokenProvider: TokenProvider = {
  getToken: () =>
    typeof localStorage !== 'undefined'
      ? localStorage.getItem('token')
      : null,
}

export function setTokenProvider(p: TokenProvider): void {
  tokenProvider = p
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
    throw new ApiError(resp.status, await resp.text())
  }
  return (await resp.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) =>
    request<T>('POST', path, body),
}
