import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import type { ConversationDetail, Feedback } from '../types'

export function ConversationDetailPage() {
  const { id = '' } = useParams(); const { token, admin } = useAuth(); const client = useQueryClient()
  const [messageId, setMessageId] = useState(''); const [rating, setRating] = useState(''); const [label, setLabel] = useState(''); const [comment, setComment] = useState('')
  const query = useQuery({ queryKey: ['conversation', id], queryFn: () => api<ConversationDetail>(`/admin/conversations/${id}`, { token }) })
  const feedback = useMutation({ mutationFn: () => api<Feedback>(`/admin/messages/${messageId}/feedback`, { method: 'POST', token, body: { rating: rating ? Number(rating) : null, label: label || null, comment: comment || null } }), onSuccess: async () => { setRating(''); setLabel(''); setComment(''); await client.invalidateQueries({ queryKey: ['conversation', id] }) } })
  if (query.isLoading) return <LoadingState />
  if (query.error || !query.data) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const detail = query.data
  function submit(event: FormEvent) { event.preventDefault(); feedback.mutate() }
  return <>
    <Link className="back-link" to="/conversations">→ العودة إلى المحادثات</Link>
    <PageHeader eyebrow={`CONVERSATION · ${detail.conversation.language.toUpperCase()}`} title={detail.conversation.guest_reference} description={`Started ${new Date(detail.conversation.started_at).toLocaleString()}`} action={<StatusBadge value={detail.conversation.escalation_status ?? detail.conversation.status} />} />
    <section className="detail-grid">
      <article className="panel timeline-panel"><div className="panel-heading"><h2>سجل الرسائل</h2><span>{detail.messages.length} messages</span></div><div className="message-timeline">{detail.messages.map(message => <article key={message.id} className={`message ${message.direction}`}><header><strong>{message.direction}</strong><time>{new Date(message.created_at).toLocaleString()}</time></header><p>{message.text}</p><footer>{message.intent && <code>{message.intent} · {message.confidence?.toFixed(2)}</code>}{message.redacted && <StatusBadge value="redacted" />}</footer></article>)}</div></article>
      <aside className="detail-aside">
        <article className="panel"><div className="panel-heading"><h2>Tool events</h2><span>{detail.tool_events.length}</span></div>{detail.tool_events.length ? <div className="compact-list">{detail.tool_events.map(event => <details key={event.id}><summary><span>{event.tool_name}</span><StatusBadge value={event.result_status} /></summary><pre>{JSON.stringify({ arguments: event.arguments, result: event.result, error: event.error_code }, null, 2)}</pre></details>)}</div> : <p className="muted">No tools used in this conversation.</p>}</article>
        <article className="panel"><div className="panel-heading"><h2>Feedback</h2><span>{detail.feedback.length}</span></div>{detail.feedback.map(item => <div className="feedback-row" key={item.id}><StatusBadge value={item.source} /><strong>{item.label ?? `${item.rating ?? '—'}/5`}</strong><p>{item.comment}</p></div>)}
          {(admin?.role === 'admin' || admin?.role === 'evaluator') && <form className="feedback-form" onSubmit={submit}><h3>إضافة تقييم بشري</h3><label>رسالة<select required value={messageId} onChange={e => setMessageId(e.target.value)}><option value="">اختر رسالة</option>{detail.messages.filter(m => m.direction === 'outbound').map(m => <option key={m.id} value={m.id}>#{m.sequence_number} · {m.text.slice(0, 35)}</option>)}</select></label><div className="field-pair"><label>Rating<select value={rating} onChange={e => setRating(e.target.value)}><option value="">—</option>{[1,2,3,4,5].map(v => <option key={v}>{v}</option>)}</select></label><label>Label<input pattern="[a-z0-9_.-]+" placeholder="grounded" value={label} onChange={e => setLabel(e.target.value)} /></label></div><label>Comment<textarea maxLength={1000} value={comment} onChange={e => setComment(e.target.value)} /></label>{feedback.error && <ErrorState error={feedback.error} />}<button className="button" disabled={feedback.isPending || (!rating && !label)}>حفظ التقييم</button></form>}
        </article>
      </aside>
    </section>
  </>
}
