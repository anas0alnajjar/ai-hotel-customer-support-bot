import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import type { Conversation, Health, Page, ServiceRequest } from '../types'

export function OverviewPage() {
  const { token, admin } = useAuth()
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/health/ready'), retry: false, refetchInterval: 30_000 })
  const conversations = useQuery({ queryKey: ['conversations', 'overview'], queryFn: () => api<Page<Conversation>>('/admin/conversations?page_size=5', { token }) })
  const requests = useQuery({ queryKey: ['requests', 'overview'], queryFn: () => api<Page<ServiceRequest>>('/admin/service-requests?status=open&page_size=5', { token }), enabled: admin?.role !== 'evaluator' })
  if (health.isLoading || conversations.isLoading || requests.isLoading) return <LoadingState />
  if (health.error || conversations.error || requests.error) return <ErrorState error={health.error ?? conversations.error ?? requests.error} retry={() => { void health.refetch(); void conversations.refetch(); void requests.refetch() }} />
  const checks = health.data?.checks ?? {}
  return <>
    <PageHeader eyebrow="OPERATIONS PULSE" title="لوحة قيادة الفندق" description="صورة لحظية عن جاهزية النظام وتدفق خدمة النزلاء." />
    <section className="hero-grid">
      <article className="hero-card primary"><p>System posture</p><div className="hero-value"><span className="pulse-ring" />{health.data?.status === 'ok' ? 'جاهز للتشغيل' : 'يتطلب الانتباه'}</div><span>API v{health.data?.version}</span></article>
      <article className="hero-card"><p>All conversations</p><strong>{conversations.data?.total ?? 0}</strong><span>مسجلة ضمن دورة الاحتفاظ</span></article>
      {admin?.role !== 'evaluator' && <article className="hero-card"><p>Open service requests</p><strong>{requests.data?.total ?? 0}</strong><span>بانتظار المعالجة</span></article>}
    </section>
    <section className="dashboard-grid">
      <article className="panel system-panel"><div className="panel-heading"><div><p className="eyebrow">SYSTEM HEALTH</p><h2>جاهزية المكونات</h2></div><StatusBadge value={health.data?.status ?? null} /></div>
        <div className="health-list">{Object.entries(checks).map(([name, status]) => <div key={name}><span className="health-icon" aria-hidden="true">{status === 'ok' || status === 'configured' ? '✓' : '!'}</span><span><strong>{name.replaceAll('_', ' ')}</strong><small>Live dependency check</small></span><StatusBadge value={status} /></div>)}</div>
      </article>
      <article className="panel"><div className="panel-heading"><div><p className="eyebrow">RECENT ACTIVITY</p><h2>آخر المحادثات</h2></div><Link className="text-link" to="/conversations">عرض الكل ←</Link></div>
        <div className="activity-list">{conversations.data?.items.map(item => <Link key={item.id} to={`/conversations/${item.id}`}><span className="avatar guest">{item.language.toUpperCase()}</span><span><strong>{item.guest_reference}</strong><small>{item.last_message_preview ?? 'No message preview'}</small></span><time>{new Date(item.last_activity_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></Link>)}</div>
      </article>
    </section>
  </>
}
