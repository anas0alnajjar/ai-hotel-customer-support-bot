import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import type { Conversation, Health, Knowledge, Page, ServiceRequest } from '../types'

export function OverviewPage() {
  const { token, admin } = useAuth()
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/health/ready'), retry: false, refetchInterval: 30_000 })
  const conversations = useQuery({ queryKey: ['conversations', 'overview'], queryFn: () => api<Page<Conversation>>('/admin/conversations?page_size=1', { token }) })
  const knowledge = useQuery({ queryKey: ['knowledge', 'overview'], queryFn: () => api<Page<Knowledge>>('/admin/knowledge?page_size=1', { token }), enabled: admin?.role === 'admin' })
  const requests = useQuery({ queryKey: ['requests', 'overview'], queryFn: () => api<Page<ServiceRequest>>('/admin/service-requests?page_size=1', { token }), enabled: admin?.role !== 'evaluator' })
  if (health.isLoading || conversations.isLoading || knowledge.isLoading || requests.isLoading) return <LoadingState />
  const error = health.error ?? conversations.error ?? knowledge.error ?? requests.error
  if (error) return <ErrorState error={error} retry={() => { void health.refetch(); void conversations.refetch(); void knowledge.refetch(); void requests.refetch() }} />
  const checks = health.data?.checks ?? {}
  const readyChecks = Object.values(checks).filter(status => status === 'ok' || status === 'configured').length
  return <>
    <PageHeader eyebrow="PROJECT STATUS" title="نظرة عامة" description="ملخص بسيط لحالة مشروع دعم عملاء الفندق والبيانات المسجلة." />
    <section className="submission-summary-grid">
      <article className="hero-card primary"><p>Project status</p><div className="hero-value"><span className="pulse-ring" />{health.data?.status === 'ok' ? 'جاهز' : 'يتطلب الانتباه'}</div><span>AI Hotel Customer Support Bot</span></article>
      <article className="hero-card"><p>Conversations</p><strong>{conversations.data?.total ?? 0}</strong><span>محادثة مسجلة</span></article>
      {admin?.role === 'admin' && <article className="hero-card"><p>Knowledge documents</p><strong>{knowledge.data?.total ?? 0}</strong><span>مستند في قاعدة المعرفة</span></article>}
      {admin?.role !== 'evaluator' && <article className="hero-card"><p>Service requests</p><strong>{requests.data?.total ?? 0}</strong><span>طلب خدمة مسجل</span></article>}
      <article className="hero-card"><p>System health</p><strong>{readyChecks}/{Object.keys(checks).length}</strong><span>فحوص جاهزة · API v{health.data?.version}</span><StatusBadge value={health.data?.status ?? null} /></article>
    </section>
  </>
}
