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

export function AuthProvider({ children }: { children: ReactNode }) {
  // Deliberately memory-only: reload/close destroys the bearer credential.
  const [session, setSession] = useState<{ token: string; admin: AdminPrincipal } | null>(null)
  const value = useMemo<AuthValue>(() => ({
    token: session?.token ?? null,
    admin: session?.admin ?? null,
    async login(identifier, password) {
      const result = await api<LoginResponse>('/admin/auth/login', {
        method: 'POST', body: { identifier, password },
      })
      setSession({ token: result.access_token, admin: result.admin })
    },
    logout() { setSession(null) },
  }), [session])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
