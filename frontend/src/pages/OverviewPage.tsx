import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import type { Booking, Conversation, Health, Knowledge, Page, ServiceRequest } from '../types'

export function OverviewPage() {
  const { token, admin } = useAuth()
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/health/ready'), retry: false, refetchInterval: 30_000 })
  const conversations = useQuery({ queryKey: ['conversations', 'overview'], queryFn: () => api<Page<Conversation>>('/admin/conversations?page_size=1', { token }) })
  const knowledge = useQuery({ queryKey: ['knowledge', 'overview'], queryFn: () => api<Page<Knowledge>>('/admin/knowledge?page_size=1', { token }), enabled: admin?.role === 'admin' })
  const bookings = useQuery({ queryKey: ['bookings', 'overview'], queryFn: () => api<Booking[]>('/admin/hotel-data/bookings', { token }), enabled: admin?.role === 'admin' })
  const requests = useQuery({ queryKey: ['requests', 'overview'], queryFn: () => api<Page<ServiceRequest>>('/admin/service-requests?page_size=1', { token }), enabled: admin?.role !== 'evaluator' })
  if (health.isLoading || conversations.isLoading || knowledge.isLoading || bookings.isLoading || requests.isLoading) return <LoadingState />
  const error = health.error ?? conversations.error ?? knowledge.error ?? bookings.error ?? requests.error
  if (error) return <ErrorState error={error} retry={() => { void health.refetch(); void conversations.refetch(); void knowledge.refetch(); void bookings.refetch(); void requests.refetch() }} />
  const checks = health.data?.checks ?? {}
  const readyChecks = Object.values(checks).filter(status => status === 'ok' || status === 'configured').length
  return <>
    <PageHeader eyebrow="DASHBOARD" title="نظرة عامة" description="أهم أرقام مشروع دعم عملاء الفندق في شاشة واحدة." />
    <section className="submission-summary-grid">
      <article className="hero-card"><p>Conversations</p><strong>{conversations.data?.total ?? 0}</strong><span>محادثة مسجلة</span></article>
      {admin?.role === 'admin' && <article className="hero-card"><p>Knowledge documents</p><strong>{knowledge.data?.total ?? 0}</strong><span>مستند في قاعدة المعرفة</span></article>}
      {admin?.role === 'admin' && <article className="hero-card"><p>Bookings</p><strong>{bookings.data?.length ?? 0}</strong><span>حجز في الفندق الافتراضي</span></article>}
      {admin?.role !== 'evaluator' && <article className="hero-card"><p>Service requests</p><strong>{requests.data?.total ?? 0}</strong><span>طلب خدمة مسجل</span></article>}
    </section>
    <section className="panel dashboard-health"><div><p className="eyebrow">SYSTEM STATUS</p><strong>{health.data?.status === 'ok' ? 'النظام جاهز' : 'النظام يحتاج انتباهاً'}</strong><span>{readyChecks}/{Object.keys(checks).length} فحوص جاهزة · API v{health.data?.version}</span></div><StatusBadge value={health.data?.status ?? null} /></section>
  </>
}
