import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination, StatusBadge } from '../components/ui'
import { api, queryString } from '../lib/api'
import type { Conversation, ConversationDetail, Page } from '../types'

export function ConversationsPage() {
  const { token } = useAuth()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const list = useQuery({
    queryKey: ['conversations', page, search, status],
    queryFn: () => api<Page<Conversation>>(`/admin/conversations${queryString({
      page,
      page_size: 20,
      search: search.length >= 2 ? search : '',
      status,
    })}`, { token }),
  })
  const detail = useQuery({
    queryKey: ['conversation', selectedId],
    queryFn: () => api<ConversationDetail>(`/admin/conversations/${selectedId}`, { token }),
    enabled: Boolean(selectedId),
  })

  return <>
    <PageHeader eyebrow="GUEST MESSAGES" title="المحادثات" description="رسالة النزيل، رد البوت، النية، ومسار Knowledge أو Tool في صفحة واحدة." />
    <section className="panel filters" aria-label="Conversation filters">
      <label className="search-field"><span aria-hidden="true">⌕</span><span className="sr-only">بحث</span><input placeholder="ابحث بالمرجع أو محتوى الرسالة…" value={search} onChange={event => { setSearch(event.target.value); setPage(1) }} /></label>
      <label><span className="sr-only">Status</span><select value={status} onChange={event => { setStatus(event.target.value); setPage(1) }}><option value="">كل الحالات</option><option value="active">Active</option><option value="closed">Closed</option><option value="escalated">Escalated</option></select></label>
    </section>
    {list.isLoading ? <LoadingState /> : list.error ? <ErrorState error={list.error} retry={() => void list.refetch()} /> : !list.data?.items.length ? <EmptyState /> : <section className="panel table-panel"><div className="table-wrap"><table><thead><tr><th>النزيل</th><th>آخر رسالة</th><th>النية</th><th>الحالة</th><th>آخر نشاط</th><th /></tr></thead><tbody>{list.data.items.map(item => <tr key={item.id} className={selectedId === item.id ? 'selected-row' : ''}><td><strong>{item.guest_reference}</strong></td><td className="preview-cell">{item.last_message_preview ?? '—'}</td><td><code>{item.latest_intent ?? 'unclassified'}</code></td><td><StatusBadge value={item.status} /></td><td><time>{new Date(item.last_activity_at).toLocaleString()}</time></td><td><button className="button ghost compact" onClick={() => setSelectedId(item.id)}>عرض</button></td></tr>)}</tbody></table></div><Pagination page={list.data.page} pages={list.data.pages} onPage={setPage} /></section>}
    {selectedId && <ConversationSummary loading={detail.isLoading} error={detail.error} detail={detail.data} retry={() => void detail.refetch()} close={() => setSelectedId(null)} />}
  </>
}

function ConversationSummary({ loading, error, detail, retry, close }: {
  loading: boolean
  error: Error | null
  detail: ConversationDetail | undefined
  retry(): void
  close(): void
}) {
  if (loading) return <LoadingState />
  if (error || !detail) return <ErrorState error={error} retry={retry} />

  const toolEvents = detail.tool_events
  const lastGuestMessage = [...detail.messages].reverse().find(message => message.direction === 'inbound')
  const lastBotResponse = [...detail.messages].reverse().find(message => message.direction === 'outbound')

  return <section className="conversation-inline-detail">
    <div className="panel-heading"><div><p className="eyebrow">CONVERSATION DETAILS</p><h2>{detail.conversation.guest_reference}</h2></div><button className="button ghost" onClick={close}>إغلاق</button></div>
    <div className="conversation-summary-grid">
      <article className="panel"><span>النية</span><strong dir="ltr">{detail.conversation.latest_intent ?? 'غير مصنف'}</strong></article>
      <article className="panel"><span>المسار</span><strong>{toolEvents.length ? 'Tool Calling' : 'Knowledge / RAG'}</strong></article>
      <article className="panel"><span>الأداة</span><strong dir="ltr">{toolEvents.at(-1)?.tool_name ?? 'لا توجد أداة'}</strong></article>
    </div>
    <div className="conversation-pair-grid">
      <article className="panel conversation-message-card guest-message"><p className="eyebrow">GUEST MESSAGE</p><h3>رسالة النزيل</h3><p>{lastGuestMessage?.text ?? 'لا توجد رسالة واردة.'}</p></article>
      <article className="panel conversation-message-card bot-message"><p className="eyebrow">BOT RESPONSE</p><h3>رد البوت</h3><p>{lastBotResponse?.text ?? 'لا يوجد رد مسجل.'}</p></article>
    </div>
    {toolEvents.length > 0 && <div className="panel simple-tool-list">{toolEvents.map(event => <div key={event.id}><strong dir="ltr">{event.tool_name}</strong><span>عملية فندقية محاكية</span><StatusBadge value={event.result_status} /></div>)}</div>}
  </section>
}
