import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination, StatusBadge } from '../components/ui'
import { api, queryString } from '../lib/api'
import type { Page, ServiceRequest } from '../types'

const transitions: Record<string, string[]> = { open: ['acknowledged', 'cancelled'], acknowledged: ['in_progress', 'cancelled'], in_progress: ['completed', 'cancelled'], completed: [], cancelled: [] }

export function ServiceRequestsPage() {
  const { token } = useAuth(); const client = useQueryClient(); const [page, setPage] = useState(1); const [status, setStatus] = useState(''); const [search, setSearch] = useState('')
  const query = useQuery({ queryKey: ['requests', page, status, search], queryFn: () => api<Page<ServiceRequest>>(`/admin/service-requests${queryString({ page, page_size: 20, status, search: search.length >= 2 ? search : '' })}`, { token }) })
  const update = useMutation({ mutationFn: ({ id, next }: { id: string; next: string }) => api<ServiceRequest>(`/admin/service-requests/${id}/status`, { method: 'PATCH', token, body: { status: next } }), onSuccess: async () => { await client.invalidateQueries({ queryKey: ['requests'] }) } })
  return <>
    <PageHeader eyebrow="HOTEL OPERATIONS" title="طلبات الخدمة" description="طلبات خدمة الغرف والصيانة التي أنشأها المساعد باستخدام Tool Calling." />
    <section className="panel filters"><label className="search-field"><span>⌕</span><span className="sr-only">Search</span><input placeholder="مرجع الطلب، الغرفة، أو الوصف…" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} /></label><select aria-label="Status" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}><option value="">كل الحالات</option>{Object.keys(transitions).map(v => <option key={v}>{v}</option>)}</select></section>
    {update.error && <ErrorState error={update.error} />}
    {query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : !query.data?.items.length ? <EmptyState /> : <section className="request-grid">{query.data.items.map(item => <article className="panel request-card" key={item.id}><header><strong dir="ltr">{item.tracking_code}</strong><StatusBadge value={item.status} /></header><p className="eyebrow">{item.request_type}</p><h2>الغرفة {item.room_number}</h2><p>{item.description}</p><dl><div><dt>النوع</dt><dd>{item.request_type}</dd></div><div><dt>الإنشاء</dt><dd>{new Date(item.created_at).toLocaleString()}</dd></div></dl>{(transitions[item.status] ?? []).length > 0 && <label>تحديث الحالة<select defaultValue="" disabled={update.isPending} onChange={e => { if (e.target.value) update.mutate({ id: item.id, next: e.target.value }); e.target.value = '' }}><option value="">اختر الحالة…</option>{transitions[item.status]?.map(next => <option value={next} key={next}>{next.replaceAll('_', ' ')}</option>)}</select></label>}</article>)}<div className="grid-pagination"><Pagination page={query.data.page} pages={query.data.pages} onPage={setPage} /></div></section>}
  </>
}
