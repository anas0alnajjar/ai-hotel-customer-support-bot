import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AppShell } from './components/AppShell'
import { I18nProvider } from './i18n/I18nContext'
import { ConversationDetailPage } from './pages/ConversationDetailPage'
import { ConversationsPage } from './pages/ConversationsPage'
import { EvaluationsPage } from './pages/EvaluationsPage'
import { KnowledgePage } from './pages/KnowledgePage'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { ServiceRequestsPage } from './pages/ServiceRequestsPage'
import type { Role } from './types'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } })

function Protected() {
  const { admin } = useAuth()
  return admin ? <Outlet /> : <Navigate to="/login" replace />
}

function RoleRoute({ roles }: { roles: Role[] }) {
  const { admin } = useAuth()
  return admin && roles.includes(admin.role) ? <Outlet /> : <Navigate to="/" replace />
}

export function App() {
  return <QueryClientProvider client={queryClient}><I18nProvider><AuthProvider><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<Protected />}><Route element={<AppShell />}>
      <Route index element={<OverviewPage />} />
      <Route path="conversations" element={<ConversationsPage />} />
      <Route path="conversations/:id" element={<ConversationDetailPage />} />
      <Route element={<RoleRoute roles={['admin']} />}><Route path="knowledge" element={<KnowledgePage />} /></Route>
      <Route element={<RoleRoute roles={['admin', 'support']} />}><Route path="requests" element={<ServiceRequestsPage />} /></Route>
      <Route element={<RoleRoute roles={['admin', 'evaluator']} />}><Route path="evaluations" element={<EvaluationsPage />} /></Route>
    </Route></Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></AuthProvider></I18nProvider></QueryClientProvider>
}
