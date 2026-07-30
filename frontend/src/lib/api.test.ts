import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, queryString, setUnauthorizedHandler } from './api'

describe('api client', () => {
  afterEach(() => {
    setUnauthorizedHandler(null)
    vi.unstubAllGlobals()
  })

  it('adds bearer access and JSON without persisting credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await api('/admin/auth/me', { token: 'secret-token' })
    const request = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(new Headers(request.headers).get('Authorization')).toBe('Bearer secret-token')
    expect(request.body).toBeUndefined()
  })

  it('returns controlled server errors and correlation IDs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'invalid_credentials' }), { status: 401, headers: { 'Content-Type': 'application/json', 'x-correlation-id': 'cid-1' } })))
    await expect(api('/admin/auth/me')).rejects.toEqual(new ApiError(401, 'invalid_credentials', 'cid-1'))
  })

  it('invalidates the restored session after an authenticated 401', async () => {
    const unauthorized = vi.fn()
    setUnauthorizedHandler(unauthorized)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'admin_authentication_required' }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    )))

    await expect(api('/admin/conversations', {
      token: 'expired-token',
    })).rejects.toMatchObject({ status: 401 })

    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it('omits empty query values', () => {
    expect(queryString({ page: 2, search: '', status: null, language: 'ar' })).toBe('?page=2&language=ar')
  })
})
