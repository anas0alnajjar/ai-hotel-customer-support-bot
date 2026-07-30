import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler } from '../lib/api'
import type { AdminPrincipal, LoginResponse } from '../types'

export type AuthStatus = 'restoring' | 'authenticated' | 'anonymous'

interface AuthValue {
  token: string | null
  admin: AdminPrincipal | null
  status: AuthStatus
  login(identifier: string, password: string): Promise<void>
  logout(): void
}

const AuthContext = createContext<AuthValue | null>(null)
const SESSION_KEY = 'hotel-admin-session'

export interface StoredSession {
  token: string
  admin: AdminPrincipal
}

export function readSession(): StoredSession | null {
  if (typeof window === 'undefined') return null
  try {
    const serialized = window.sessionStorage.getItem(SESSION_KEY)
    if (!serialized) return null
    const value = JSON.parse(serialized) as Partial<StoredSession>
    if (
      typeof value.token !== 'string'
      || !value.token
      || !value.admin
      || typeof value.admin.id !== 'string'
      || typeof value.admin.email !== 'string'
      || typeof value.admin.username !== 'string'
      || typeof value.admin.role !== 'string'
    ) {
      window.sessionStorage.removeItem(SESSION_KEY)
      return null
    }
    return value as StoredSession
  } catch {
    window.sessionStorage.removeItem(SESSION_KEY)
    return null
  }
}

export function storeSession(session: StoredSession | null): void {
  if (typeof window === 'undefined') return
  if (session) {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
  } else {
    window.sessionStorage.removeItem(SESSION_KEY)
  }
}

export async function authenticate(identifier: string, password: string): Promise<StoredSession> {
  const result = await api<LoginResponse>('/admin/auth/login', {
    method: 'POST', body: { identifier, password },
  })
  return { token: result.access_token, admin: result.admin }
}

export async function restoreSession(session: StoredSession): Promise<StoredSession> {
  const admin = await api<AdminPrincipal>('/admin/auth/me', { token: session.token })
  return { token: session.token, admin }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(readSession)
  const [status, setStatus] = useState<AuthStatus>(
    () => session ? 'restoring' : 'anonymous',
  )

  useEffect(() => {
    let active = true
    const stored = readSession()
    if (!stored) {
      setStatus('anonymous')
      return () => { active = false }
    }
    void restoreSession(stored)
      .then((restored) => {
        if (!active) return
        storeSession(restored)
        setSession(restored)
        setStatus('authenticated')
      })
      .catch(() => {
        if (!active) return
        storeSession(null)
        setSession(null)
        setStatus('anonymous')
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      storeSession(null)
      setSession(null)
      setStatus('anonymous')
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  const value = useMemo<AuthValue>(() => ({
    token: session?.token ?? null,
    admin: session?.admin ?? null,
    status,
    async login(identifier, password) {
      const next = await authenticate(identifier, password)
      storeSession(next)
      setSession(next)
      setStatus('authenticated')
    },
    logout() {
      storeSession(null)
      setSession(null)
      setStatus('anonymous')
    },
  }), [session, status])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
