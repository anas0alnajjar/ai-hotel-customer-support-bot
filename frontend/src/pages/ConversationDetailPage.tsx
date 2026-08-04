import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import type { ConversationDetail } from '../types'

export function ConversationDetailPage() {
  const { id = '' } = useParams()
  const { token } = useAuth()
  const query = useQuery({
    queryKey: ['conversation', id],
    queryFn: () => api<ConversationDetail>(`/admin/conversations/${id}`, { token }),
  })
  if (query.isLoading) return <LoadingState />
  if (query.error || !query.data) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const detail = query.data
  const selectedIntent = detail.conversation.latest_intent ?? 'غير مصنف'
  const toolEvents = detail.tool_events
  const path = toolEvents.length > 0 ? 'Tool Calling' : 'Knowledge / RAG'
  const lastGuestMessage = [...detail.messages].reverse().find(message => message.direction === 'inbound')
  const lastBotResponse = [...detail.messages].reverse().find(message => message.direction === 'outbound')

  return <>
    <Link className="back-link" to="/conversations">→ العودة إلى المحادثات</Link>
    <PageHeader
      eyebrow="CONVERSATION"
      title={detail.conversation.guest_reference}
      description="عرض مبسط للرسالة والرد والنية والمسار الذي اختاره النظام."
      action={<StatusBadge value={detail.conversation.status} />}
    />
    <section className="conversation-summary-grid">
      <article className="panel"><span>النية المختارة</span><strong dir="ltr">{selectedIntent}</strong></article>
      <article className="panel"><span>مسار المعالجة</span><strong>{path}</strong></article>
      <article className="panel"><span>النتيجة التنفيذية</span><strong>{toolEvents.length ? `${toolEvents.length} tool event` : 'لا توجد أداة منفذة'}</strong></article>
    </section>
    <section className="conversation-pair-grid">
      <article className="panel conversation-message-card guest-message"><p className="eyebrow">GUEST MESSAGE</p><h2>رسالة النزيل</h2><p>{lastGuestMessage?.text ?? 'لا توجد رسالة واردة.'}</p></article>
      <article className="panel conversation-message-card bot-message"><p className="eyebrow">BOT RESPONSE</p><h2>رد المساعد</h2><p>{lastBotResponse?.text ?? 'لا يوجد رد مسجل.'}</p></article>
    </section>
    <section className="panel simplified-path-detail">
      <div className="panel-heading"><div><p className="eyebrow">EVIDENCE OR TOOL</p><h2>{toolEvents.length ? 'الأداة المنفذة' : 'مسار المعرفة'}</h2></div></div>
      {toolEvents.length ? <div className="simple-tool-list">{toolEvents.map(event => <div key={event.id}><strong dir="ltr">{event.tool_name}</strong><span>Room/operation request</span><StatusBadge value={event.result_status} /></div>)}</div> : <p className="knowledge-path-note">استُخدم مسار Knowledge/RAG ولم تُنفذ أداة فندقية. يعرض رد المساعد أعلاه النتيجة المؤرضة، بينما تبقى المعرّفات التقنية التفصيلية خارج واجهة المناقشة المبسطة.</p>}
    </section>
  </>
}
