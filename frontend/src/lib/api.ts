export class ApiError extends Error {
  constructor(public status: number, public code: string, public correlationId: string | null) {
    super(code)
    this.name = 'ApiError'
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & { body?: unknown; token?: string | null }
type UnauthorizedHandler = () => void

let unauthorizedHandler: UnauthorizedHandler | null = null

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body !== undefined) headers.set('Content-Type', 'application/json')
  if (options.token) headers.set('Authorization', `Bearer ${options.token}`)
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (!response.ok) {
    let code = `http_${response.status}`
    try {
      const data = await response.json() as { detail?: string }
      if (typeof data.detail === 'string') code = data.detail
    } catch { /* retain controlled fallback */ }
    if (response.status === 401 && options.token) unauthorizedHandler?.()
    throw new ApiError(response.status, code, response.headers.get('x-correlation-id'))
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function queryString(values: Record<string, string | number | null | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}
