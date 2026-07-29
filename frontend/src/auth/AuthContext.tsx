import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import type { AdminPrincipal, LoginResponse } from '../types'

interface AuthValue {
  token: string | null
  admin: AdminPrincipal | null
  login(identifier: string, password: string): Promise<void>
  logout(): void
}

const AuthContext = createContext<AuthValue | null>(null)
const SESSION_KEY = 'hotel-admin-session'

interface StoredSession {
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(readSession)
  const value = useMemo<AuthValue>(() => ({
    token: session?.token ?? null,
    admin: session?.admin ?? null,
    async login(identifier, password) {
      const result = await api<LoginResponse>('/admin/auth/login', {
        method: 'POST', body: { identifier, password },
      })
      const next = { token: result.access_token, admin: result.admin }
      storeSession(next)
      setSession(next)
    },
    logout() {
      storeSession(null)
      setSession(null)
    },
  }), [session])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
