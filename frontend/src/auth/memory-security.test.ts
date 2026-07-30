import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  authenticate,
  readSession,
  restoreSession,
  storeSession,
} from './AuthContext'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('browser credential policy', () => {
  it('uses tab-scoped storage so authentication survives refresh but not browser close', () => {
    const source = readFileSync(new URL('./AuthContext.tsx', import.meta.url), 'utf8')
    expect(source).toContain('window.sessionStorage.getItem')
    expect(source).toContain('window.sessionStorage.setItem')
    expect(source).toContain('window.sessionStorage.removeItem')
    expect(source).not.toMatch(/localStorage|indexedDB/)
    expect(source).toContain('useState<StoredSession | null>(readSession)')
  })

  it('restores a valid authenticated session after provider reinitialization', () => {
    const values = new Map<string, string>()
    vi.stubGlobal('window', {
      sessionStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
      },
    })
    const session = {
      token: 'signed-access-token',
      admin: {
        id: 'admin-id',
        email: 'admin@example.invalid',
        username: 'admin',
        role: 'admin' as const,
      },
    }

    storeSession(session)

    expect(readSession()).toEqual(session)
    storeSession(null)
    expect(readSession()).toBeNull()
  })

  it('authenticates, validates a reloaded session, and rejects an invalid token', async () => {
    const principal = {
      id: 'admin-id',
      email: 'admin@example.invalid',
      username: 'admin',
      role: 'admin' as const,
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: 'signed-access-token',
        token_type: 'bearer',
        expires_in: 900,
        admin: principal,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(principal), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        detail: 'admin_authentication_required',
      }), { status: 401, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    const loggedIn = await authenticate('admin', 'long-enough-password')
    const restored = await restoreSession(loggedIn)

    expect(restored).toEqual(loggedIn)
    const restoreRequest = fetchMock.mock.calls[1]?.[1] as RequestInit
    expect(new Headers(restoreRequest.headers).get('Authorization')).toBe(
      'Bearer signed-access-token',
    )
    await expect(restoreSession({
      ...loggedIn,
      token: 'invalid-token',
    })).rejects.toMatchObject({ status: 401 })
  })

  it('guards protected routes until server-side restoration finishes', () => {
    const source = readFileSync(new URL('../App.tsx', import.meta.url), 'utf8')
    expect(source).toContain("status === 'restoring'")
    expect(source.indexOf("status === 'restoring'")).toBeLessThan(
      source.indexOf('return admin ?'),
    )
  })
})
