import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  StatusBadge,
} from '../components/ui'
import { api, queryString } from '../lib/api'
import type { Knowledge, KnowledgeDetail, KnowledgeRevision, Page } from '../types'

type Confirmation =
  | { action: 'archive'; documentId: string }
  | { action: 'restore'; documentId: string }
  | { action: 'approve'; documentId: string; revision: KnowledgeRevision }

export function documentLifecycleAction(status: string): 'archive' | 'restore' {
  return status === 'archived' ? 'restore' : 'archive'
}

export function effectiveRevision(detail: KnowledgeDetail): KnowledgeRevision | null {
  return detail.revisions.find(revision => revision.effective) ?? null
}

export function pendingDraft(detail: KnowledgeDetail): KnowledgeRevision | null {
  return detail.revisions.find(revision => revision.status === 'draft') ?? null
}

export function KnowledgePage() {
  const { token } = useAuth()
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const list = useQuery({
    queryKey: ['knowledge', page, search],
    queryFn: () => api<Page<Knowledge>>(`/admin/knowledge${queryString({
      page,
      page_size: 20,
      search: search.length >= 2 ? search : '',
    })}`, { token }),
  })
  const detail = useQuery({
    queryKey: ['knowledge-detail', selected],
    queryFn: () => api<KnowledgeDetail>(`/admin/knowledge/${selected}`, { token }),
    enabled: Boolean(selected),
  })

  const invalidate = async () => {
    await client.invalidateQueries({ queryKey: ['knowledge'] })
    if (selected) await client.invalidateQueries({ queryKey: ['knowledge-detail', selected] })
  }
  const finish = async (message: string) => {
    setConfirmation(null)
    setSuccess(message)
    await invalidate()
  }
  const approve = useMutation({
    mutationFn: ({ documentId, revisionId }: { documentId: string; revisionId: string }) =>
      api(`/admin/knowledge/${documentId}/revisions/${revisionId}/approve`, {
        method: 'POST', token,
      }),
    onSuccess: async () => finish('تم اعتماد المحتوى وبدأت مزامنة FAISS.'),
  })
  const archive = useMutation({
    mutationFn: (id: string) => api(`/admin/knowledge/${id}`, { method: 'DELETE', token }),
    onSuccess: async () => finish('تمت أرشفة المستند واستبعاده من الاسترجاع.'),
  })
  const restore = useMutation({
    mutationFn: (id: string) => api(`/admin/knowledge/${id}/restore`, {
      method: 'POST', token,
    }),
    onSuccess: async () => finish('تمت استعادة المستند وبدأت مزامنة FAISS.'),
  })
  const reindex = useMutation({
    mutationFn: () => api<{ chunk_count: number }>('/admin/knowledge/reindex', {
      method: 'POST', token,
    }),
    onSuccess: async result => {
      setSuccess(`بدأت إعادة بناء FAISS (${result.chunk_count} مقطع).`)
      await invalidate()
    },
  })

  const confirm = () => {
    if (!confirmation) return
    if (confirmation.action === 'archive') archive.mutate(confirmation.documentId)
    else if (confirmation.action === 'restore') restore.mutate(confirmation.documentId)
    else approve.mutate({
      documentId: confirmation.documentId,
      revisionId: confirmation.revision.id,
    })
  }
  const firstError = [approve.error, archive.error, restore.error, reindex.error].find(Boolean)
  const currentDetail = detail.data
  const effective = currentDetail ? effectiveRevision(currentDetail) : null
  const draft = currentDetail ? pendingDraft(currentDetail) : null
  const visibleContent = draft ?? effective

  return <>
    <PageHeader
      eyebrow="RAG KNOWLEDGE"
      title="قاعدة المعرفة"
      description="راجع المحتوى المعتمد، اضبط حالة المستند، وأعد بناء فهرس FAISS."
      action={<button className="button secondary" onClick={() => reindex.mutate()} disabled={reindex.isPending}>إعادة بناء FAISS</button>}
    />
    {firstError && <ErrorState error={firstError} />}
    {success && <div className="success-banner" role="status">{success}</div>}
    <section className="panel filters">
      <label className="search-field"><span aria-hidden="true">⌕</span><span className="sr-only">بحث</span><input placeholder="ابحث في المستندات…" value={search} onChange={event => { setSearch(event.target.value); setPage(1) }} /></label>
    </section>
    {list.isLoading ? <LoadingState /> : list.error ? <ErrorState error={list.error} retry={() => void list.refetch()} /> : !list.data?.items.length ? <EmptyState /> : <section className="knowledge-layout">
      <div className="panel knowledge-list">
        {list.data.items.map(item => <button key={item.id} className={selected === item.id ? 'selected' : ''} onClick={() => setSelected(item.id)}>
          <span><strong>{item.title}</strong><small>{item.language.toUpperCase()}</small></span>
          <StatusBadge value={item.status} />
        </button>)}
        <Pagination page={list.data.page} pages={list.data.pages} onPage={setPage} />
      </div>
      <article className="panel knowledge-detail">
        {!selected ? <EmptyState title="اختر مستنداً" body="سيظهر محتواه وحالته هنا." /> : detail.isLoading ? <LoadingState /> : detail.error || !currentDetail ? <ErrorState error={detail.error} /> : <>
          <div className="panel-heading knowledge-heading">
            <div><p className="eyebrow">KNOWLEDGE DOCUMENT</p><h2>{currentDetail.document.title}</h2></div>
            <button className={`button ${currentDetail.document.status === 'archived' ? '' : 'danger subtle'}`} onClick={() => setConfirmation({ action: documentLifecycleAction(currentDetail.document.status), documentId: currentDetail.document.id })}>
              {currentDetail.document.status === 'archived' ? 'استعادة' : 'أرشفة'}
            </button>
          </div>
          <KnowledgeStatusSummary detail={currentDetail} />
          <section className="knowledge-current-content">
            <div className="panel-heading"><h3>المحتوى الحالي</h3>{visibleContent && <StatusBadge value={visibleContent.status} />}</div>
            <p>{visibleContent?.content ?? 'لا يوجد محتوى متاح.'}</p>
          </section>
          {draft && currentDetail.document.status !== 'archived' && <section className="compact-review">
            <div><strong>توجد مسودة بانتظار الاعتماد</strong><p>راجع المحتوى أعلاه ثم اعتمده ليصبح مؤهلاً للاسترجاع.</p></div>
            <button className="button" onClick={() => setConfirmation({ action: 'approve', documentId: currentDetail.document.id, revision: draft })}>اعتماد</button>
          </section>}
        </>}
      </article>
    </section>}
    <ConfirmDialog
      open={Boolean(confirmation)}
      title={confirmation?.action === 'archive' ? 'أرشفة المستند؟' : confirmation?.action === 'restore' ? 'استعادة المستند؟' : 'اعتماد المحتوى؟'}
      body={confirmation?.action === 'archive' ? 'سيتوقف استخدام المستند في إجابات RAG مع بقاء بياناته محفوظة.' : confirmation?.action === 'restore' ? 'سيعود المستند المعتمد إلى مسار الاسترجاع بعد مزامنة FAISS.' : 'سيصبح هذا المحتوى هو المحتوى المعتمد المستخدم في RAG.'}
      confirmLabel={confirmation?.action === 'archive' ? 'أرشفة' : confirmation?.action === 'restore' ? 'استعادة' : 'اعتماد'}
      danger={confirmation?.action === 'archive'}
      busy={archive.isPending || restore.isPending || approve.isPending}
      onClose={() => setConfirmation(null)}
      onConfirm={confirm}
    />
  </>
}

export function KnowledgeStatusSummary({ detail }: { detail: KnowledgeDetail }) {
  const effective = effectiveRevision(detail)
  return <dl className="knowledge-status-grid simplified-status-grid">
    <div><dt>حالة المستند</dt><dd>{detail.document.status === 'archived' ? 'مؤرشف' : detail.document.status === 'approved' ? 'نشط' : 'مسودة'}</dd></div>
    <div><dt>المحتوى المعتمد الفعّال</dt><dd>{effective ? `Version ${effective.version}` : 'غير معتمد بعد'}</dd></div>
    <div><dt>الاسترجاع</dt><dd>{detail.retrieval_eligible ? 'متاح عبر RAG' : 'غير متاح حالياً'}</dd></div>
    <div><dt>FAISS</dt><dd>{detail.faiss_sync_status === 'synchronized' ? 'متزامن' : detail.faiss_sync_status === 'building' ? 'جارٍ التحديث' : 'يحتاج إعادة بناء'}</dd></div>
  </dl>
}
