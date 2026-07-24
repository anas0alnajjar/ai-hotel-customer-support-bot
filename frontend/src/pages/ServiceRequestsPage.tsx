import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination, StatusBadge } from '../components/ui'
import { api, queryString } from '../lib/api'
import type { Page, ServiceRequest } from '../types'

const transitions: Record<string, string[]> = { open: ['acknowledged', 'cancelled'], acknowledged: ['in_progress', 'cancelled'], in_progress: ['completed', 'cancelled'], completed: [], cancelled: [] }

export function ServiceRequestsPage() {
  const { token } = useAuth(); const client = useQueryClient(); const [page, setPage] = useState(1); const [status, setStatus] = useState(''); const [urgency, setUrgency] = useState(''); const [search, setSearch] = useState('')
  const query = useQuery({ queryKey: ['requests', page, status, urgency, search], queryFn: () => api<Page<ServiceRequest>>(`/admin/service-requests${queryString({ page, page_size: 20, status, urgency, search: search.length >= 2 ? search : '' })}`, { token }) })
  const update = useMutation({ mutationFn: ({ id, next }: { id: string; next: string }) => api<ServiceRequest>(`/admin/service-requests/${id}/status`, { method: 'PATCH', token, body: { status: next } }), onSuccess: async () => { await client.invalidateQueries({ queryKey: ['requests'] }) } })
  return <>
    <PageHeader eyebrow="HOTEL OPERATIONS" title="طلبات الخدمة" description="تابع طلبات خدمة الغرف والصيانة ضمن انتقالات حالة محكومة ومدققة." />
    <section className="panel filters"><label className="search-field"><span>⌕</span><span className="sr-only">Search</span><input placeholder="غرفة، فئة، أو وصف…" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} /></label><select aria-label="Status" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}><option value="">كل الحالات</option>{Object.keys(transitions).map(v => <option key={v}>{v}</option>)}</select><select aria-label="Urgency" value={urgency} onChange={e => { setUrgency(e.target.value); setPage(1) }}><option value="">كل الأولويات</option><option value="low">low</option><option value="normal">normal</option><option value="high">high</option><option value="emergency">emergency</option></select></section>
    {update.error && <ErrorState error={update.error} />}
    {query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : !query.data?.items.length ? <EmptyState /> : <section className="request-grid">{query.data.items.map(item => <article className="panel request-card" key={item.id}><header><span className={`urgency urgency-${item.urgency}`}>{item.urgency}</span><StatusBadge value={item.status} /></header><p className="eyebrow">{item.request_type} · ROOM {item.room_number}</p><h2>{item.category}</h2><p>{item.description}</p><dl><div><dt>Tracking</dt><dd>{item.tracking_code}</dd></div><div><dt>Created</dt><dd>{new Date(item.created_at).toLocaleString()}</dd></div></dl>{(transitions[item.status] ?? []).length > 0 && <label>نقل الحالة<select defaultValue="" disabled={update.isPending} onChange={e => { if (e.target.value) update.mutate({ id: item.id, next: e.target.value }); e.target.value = '' }}><option value="">اختر الإجراء…</option>{transitions[item.status]?.map(next => <option value={next} key={next}>{next.replaceAll('_', ' ')}</option>)}</select></label>}</article>)}<div className="grid-pagination"><Pagination page={query.data.page} pages={query.data.pages} onPage={setPage} /></div></section>}
  </>
}
