import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination, StatusBadge } from '../components/ui'
import { api, queryString } from '../lib/api'
import type { Conversation, Page } from '../types'

export function ConversationsPage() {
  const { token } = useAuth()
  const [page, setPage] = useState(1); const [search, setSearch] = useState(''); const [status, setStatus] = useState('')
  const query = useQuery({ queryKey: ['conversations', page, search, status], queryFn: () => api<Page<Conversation>>(`/admin/conversations${queryString({ page, page_size: 20, search: search.length >= 2 ? search : '', status })}`, { token }) })
  return <>
    <PageHeader eyebrow="GUEST MESSAGES" title="المحادثات" description="استعرض رسالة النزيل ورد المساعد والنية ومسار Knowledge أو Tool Calling." />
    <section className="panel filters" aria-label="Conversation filters">
      <label className="search-field"><span aria-hidden="true">⌕</span><span className="sr-only">بحث</span><input placeholder="ابحث بالمرجع أو محتوى الرسالة…" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} /></label>
      <label><span className="sr-only">Status</span><select value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}><option value="">كل الحالات</option><option value="active">Active</option><option value="closed">Closed</option><option value="escalated">Escalated</option></select></label>
    </section>
    {query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : !query.data?.items.length ? <EmptyState /> : <section className="panel table-panel"><div className="table-wrap"><table><thead><tr><th>النزيل</th><th>آخر رسالة</th><th>النية</th><th>الحالة</th><th>آخر نشاط</th><th /></tr></thead><tbody>{query.data.items.map(item => <tr key={item.id}><td><strong>{item.guest_reference}</strong></td><td className="preview-cell">{item.last_message_preview ?? '—'}</td><td><code>{item.latest_intent ?? 'unclassified'}</code></td><td><StatusBadge value={item.status} /></td><td><time>{new Date(item.last_activity_at).toLocaleString()}</time></td><td><Link className="icon-link" aria-label={`Open ${item.guest_reference}`} to={`/conversations/${item.id}`}>←</Link></td></tr>)}</tbody></table></div><Pagination page={query.data.page} pages={query.data.pages} onPage={setPage} /></section>}
  </>
}
