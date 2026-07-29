import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readSession, storeSession } from './AuthContext'

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
})
