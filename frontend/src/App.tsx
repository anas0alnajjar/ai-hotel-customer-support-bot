import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AppShell } from './components/AppShell'
import { I18nProvider } from './i18n/I18nContext'
import { ConversationsPage } from './pages/ConversationsPage'
import { KnowledgePage } from './pages/KnowledgePage'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import type { Role } from './types'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } })

function Protected() {
  const { admin, status } = useAuth()
  if (status === 'restoring') return <main className="route-loading" aria-busy="true">Restoring secure session…</main>
  return admin ? <Outlet /> : <Navigate to="/login" replace />
}

function RoleRoute({ roles }: { roles: Role[] }) {
  const { admin, status } = useAuth()
  if (status === 'restoring') return null
  return admin && roles.includes(admin.role) ? <Outlet /> : <Navigate to="/" replace />
}

export function App() {
  return <QueryClientProvider client={queryClient}><I18nProvider><AuthProvider><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<Protected />}><Route element={<AppShell />}>
      <Route index element={<OverviewPage />} />
      <Route path="conversations" element={<ConversationsPage />} />
      <Route element={<RoleRoute roles={['admin']} />}><Route path="knowledge" element={<KnowledgePage />} /></Route>
    </Route></Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></AuthProvider></I18nProvider></QueryClientProvider>
}
