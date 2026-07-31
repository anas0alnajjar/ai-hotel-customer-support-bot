import { useEffect, useState, type FormEvent } from 'react'
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

type EditorState =
  | { mode: 'create' }
  | { mode: 'new-version'; source: KnowledgeRevision }
  | { mode: 'edit-draft'; revision: KnowledgeRevision }

type Confirmation =
  | { action: 'archive'; documentId: string }
  | { action: 'restore'; documentId: string }
  | { action: 'approve'; documentId: string; revision: KnowledgeRevision }

export function documentLifecycleAction(status: string): 'archive' | 'restore' {
  return status === 'archived' ? 'restore' : 'archive'
}

export function revisionStatusLabel(revision: KnowledgeRevision): string {
  if (revision.effective) return 'النسخة الفعالة المعتمدة'
  if (revision.status === 'historical') return 'نسخة تاريخية معتمدة'
  return 'مسودة'
}

export function canCreateNewVersion(status: string): boolean {
  return status !== 'archived'
}

export function revisionActions(revision: KnowledgeRevision): Array<'edit' | 'approve' | 'reactivate'> {
  const actions: Array<'edit' | 'approve' | 'reactivate'> = []
  if (revision.editable) actions.push('edit')
  if (!revision.effective) actions.push(revision.status === 'historical' ? 'reactivate' : 'approve')
  return actions
}

export function KnowledgePage() {
  const { token } = useAuth()
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [selectedRevision, setSelectedRevision] = useState<string | null>(null)
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [title, setTitle] = useState('')
  const [language, setLanguage] = useState('ar')
  const [content, setContent] = useState('')
  const [success, setSuccess] = useState<string | null>(null)

  const list = useQuery({
    queryKey: ['knowledge', page, search],
    queryFn: () => api<Page<Knowledge>>(`/admin/knowledge${queryString({ page, page_size: 20, search: search.length >= 2 ? search : '' })}`, { token }),
  })
  const detail = useQuery({
    queryKey: ['knowledge-detail', selected],
    queryFn: () => api<KnowledgeDetail>(`/admin/knowledge/${selected}`, { token }),
    enabled: Boolean(selected),
  })

  useEffect(() => {
    if (!detail.data) return
    const current = detail.data.document.current_revision_id
    if (!selectedRevision || !detail.data.revisions.some(item => item.id === selectedRevision)) {
      setSelectedRevision(current ?? detail.data.revisions[0]?.id ?? null)
    }
  }, [detail.data, selectedRevision])

  const invalidate = async () => {
    await client.invalidateQueries({ queryKey: ['knowledge'] })
    if (selected) await client.invalidateQueries({ queryKey: ['knowledge-detail', selected] })
  }
  const finish = async (message: string) => {
    setEditor(null)
    setConfirmation(null)
    setSuccess(message)
    await invalidate()
  }

  const create = useMutation({
    mutationFn: () => api('/admin/knowledge', {
      method: 'POST', token, body: { title, language, source_format: 'plain_text', content },
    }),
    onSuccess: async () => {
      setTitle(''); setContent('')
      await finish('تم إنشاء المستند ونسخته الأولى كمسودة.')
    },
  })
  const createVersion = useMutation({
    mutationFn: (documentId: string) => api(`/admin/knowledge/${documentId}`, {
      method: 'PATCH', token, body: { content },
    }),
    onSuccess: async () => finish('تم إنشاء نسخة مسودة جديدة تحت المستند نفسه.'),
  })
  const editDraft = useMutation({
    mutationFn: ({ documentId, revisionId }: { documentId: string; revisionId: string }) => api(`/admin/knowledge/${documentId}/revisions/${revisionId}`, {
      method: 'PATCH', token, body: { content },
    }),
    onSuccess: async () => finish('تم حفظ تعديلات المسودة.'),
  })
  const approve = useMutation({
    mutationFn: ({ documentId, revisionId }: { documentId: string; revisionId: string }) => api(`/admin/knowledge/${documentId}/revisions/${revisionId}/approve`, { method: 'POST', token }),
    onSuccess: async () => finish('تم اعتماد النسخة وبدأت مزامنة FAISS الآمنة.'),
  })
  const archive = useMutation({
    mutationFn: (id: string) => api(`/admin/knowledge/${id}`, { method: 'DELETE', token }),
    onSuccess: async () => finish('تمت أرشفة المستند مع حفظ كل نسخه.'),
  })
  const restore = useMutation({
    mutationFn: (id: string) => api(`/admin/knowledge/${id}/restore`, { method: 'POST', token }),
    onSuccess: async () => finish('تمت استعادة المستند نفسه وبدأت مزامنة FAISS.'),
  })
  const reindex = useMutation({
    mutationFn: () => api<{ chunk_count: number }>('/admin/knowledge/reindex', { method: 'POST', token }),
    onSuccess: async result => {
      setSuccess(`بدأت إعادة بناء FAISS (${result.chunk_count} مقطع).`)
      await invalidate()
    },
  })

  const currentDetail = detail.data
  const openNewVersion = () => {
    if (!currentDetail) return
    const existingDraft = currentDetail.revisions.find(item => item.editable)
    if (existingDraft) {
      setContent(existingDraft.content)
      setEditor({ mode: 'edit-draft', revision: existingDraft })
      return
    }
    const source = currentDetail.revisions.find(item => item.effective) ?? currentDetail.revisions[0]
    if (!source) return
    setContent(source.content)
    setEditor({ mode: 'new-version', source })
  }
  const openDraft = (revision: KnowledgeRevision) => {
    setContent(revision.content)
    setEditor({ mode: 'edit-draft', revision })
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!editor) return
    if (editor.mode === 'create') create.mutate()
    else if (editor.mode === 'new-version' && selected) createVersion.mutate(selected)
    else if (editor.mode === 'edit-draft' && selected) {
      editDraft.mutate({ documentId: selected, revisionId: editor.revision.id })
    }
  }
  const confirm = () => {
    if (!confirmation) return
    if (confirmation.action === 'archive') archive.mutate(confirmation.documentId)
    else if (confirmation.action === 'restore') restore.mutate(confirmation.documentId)
    else approve.mutate({ documentId: confirmation.documentId, revisionId: confirmation.revision.id })
  }
  const errors = [create.error, createVersion.error, editDraft.error, approve.error, archive.error, restore.error, reindex.error]
  const firstError = errors.find(Boolean)
  const mutationBusy = create.isPending || createVersion.isPending || editDraft.isPending
  const unchangedNewVersion = editor?.mode === 'new-version' && content.trim() === editor.source.content.trim()

  return <>
    <PageHeader
      eyebrow="GROUNDING CONTROL"
      title="قاعدة المعرفة"
      description="أدر دورة حياة المستند والنسخ بصورة مستقلة، ولا تُسترجع إلا النسخة الفعالة المعتمدة."
      action={<div className="action-row knowledge-page-actions">
        <button className="button secondary" onClick={() => reindex.mutate()} disabled={reindex.isPending}>إعادة بناء FAISS</button>
        <button className="button" onClick={() => { setContent(''); setEditor({ mode: 'create' }) }}>+ مستند جديد</button>
      </div>}
    />
    {firstError && <ErrorState error={firstError} />}
    {success && <div className="success-banner" role="status">{success}</div>}
    <section className="panel filters">
      <label className="search-field"><span aria-hidden="true">⌕</span><span className="sr-only">Search</span><input placeholder="ابحث في العناوين…" value={search} onChange={event => { setSearch(event.target.value); setPage(1) }} /></label>
    </section>
    {list.isLoading ? <LoadingState /> : list.error ? <ErrorState error={list.error} retry={() => void list.refetch()} /> : !list.data?.items.length ? <EmptyState /> : <section className="knowledge-layout">
      <div className="panel knowledge-list">
        {list.data.items.map(item => <button key={item.id} className={selected === item.id ? 'selected' : ''} onClick={() => { setSelected(item.id); setSelectedRevision(item.current_revision_id) }}>
          <span><strong>{item.title}</strong><small>{item.language.toUpperCase()} · {item.revision_count} نسخ</small></span><StatusBadge value={item.status} />
        </button>)}
        <Pagination page={list.data.page} pages={list.data.pages} onPage={setPage} />
      </div>
      <article className="panel knowledge-detail">
        {!selected ? <EmptyState title="اختر مستنداً" body="ستظهر دورة الحياة وسجل النسخ هنا." /> : detail.isLoading ? <LoadingState /> : detail.error || !currentDetail ? <ErrorState error={detail.error} /> : <>
          <div className="panel-heading knowledge-heading">
            <div><p className="eyebrow">DOCUMENT</p><h2>{currentDetail.document.title}</h2></div>
            <div className="action-row knowledge-actions">
              {canCreateNewVersion(currentDetail.document.status) && <button className="button secondary" onClick={openNewVersion}>نسخة جديدة</button>}
              <button className={`button ${currentDetail.document.status === 'archived' ? '' : 'danger subtle'}`} onClick={() => setConfirmation({ action: documentLifecycleAction(currentDetail.document.status), documentId: currentDetail.document.id })}>
                {currentDetail.document.status === 'archived' ? 'استعادة' : 'أرشفة'}
              </button>
            </div>
          </div>
          <KnowledgeStatusSummary detail={currentDetail} selectedRevision={selectedRevision} />
          <h3 className="section-title">سجل النسخ</h3>
          <div className="revision-list">
            {currentDetail.revisions.map(revision => <article className={`revision-card ${revision.id === selectedRevision ? 'selected' : ''}`} key={revision.id}>
              <div className="revision-card-heading">
                <button className="revision-selector" onClick={() => setSelectedRevision(revision.id)}>
                  <strong>Version {revision.version}</strong>
                  <small>{revisionStatusLabel(revision)} · {new Date(revision.created_at).toLocaleString()}</small>
                </button>
                <div className="status-chip-row">
                  <StatusBadge value={revision.status} />
                  {revision.indexed_in_faiss && <span className="badge badge-positive">FAISS</span>}
                </div>
              </div>
              <details open={revision.id === selectedRevision}>
                <summary>فتح محتوى النسخة وتفاصيلها</summary>
                <p>{revision.content}</p>
                <dl className="revision-meta">
                  <div><dt>تاريخ الإنشاء</dt><dd>{new Date(revision.created_at).toLocaleString()}</dd></div>
                  <div><dt>تاريخ الاعتماد</dt><dd>{revision.approved_at ? new Date(revision.approved_at).toLocaleString() : 'غير معتمدة بعد'}</dd></div>
                  <div><dt>المنشئ</dt><dd><TechnicalValue value={revision.created_by ?? 'غير مسجل'} /></dd></div>
                  <div><dt>SHA</dt><dd><TechnicalValue value={revision.checksum} copy /></dd></div>
                </dl>
                <div className="action-row revision-actions">
                  {revisionActions(revision).includes('edit') && <button className="button small secondary" onClick={() => openDraft(revision)}>تعديل المسودة</button>}
                  {currentDetail.document.status !== 'archived' && (revisionActions(revision).includes('approve') || revisionActions(revision).includes('reactivate')) && <button className="button small" onClick={() => setConfirmation({ action: 'approve', documentId: currentDetail.document.id, revision })}>
                    {revisionActions(revision).includes('reactivate') ? 'اعتماد هذه النسخة' : 'اعتماد النسخة'}
                  </button>}
                </div>
              </details>
            </article>)}
          </div>
        </>}
      </article>
    </section>}
    {editor && <div className="dialog-backdrop"><form className="dialog editor-dialog" role="dialog" aria-modal="true" aria-labelledby="knowledge-editor-title" onSubmit={submit}>
      <h2 id="knowledge-editor-title">{editor.mode === 'create' ? 'مستند معرفة جديد' : editor.mode === 'new-version' ? 'نسخة جديدة' : `تعديل Version ${editor.revision.version}`}</h2>
      {editor.mode === 'create' && <>
        <label>العنوان<input required minLength={3} maxLength={255} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <label>اللغة<select value={language} onChange={event => setLanguage(event.target.value)}><option value="ar">العربية</option><option value="en">English</option></select></label>
      </>}
      <label>المحتوى<textarea required minLength={20} maxLength={100000} rows={12} value={content} onChange={event => setContent(event.target.value)} /></label>
      {unchangedNewVersion && <p className="form-help">عدّل المحتوى قبل إنشاء نسخة جديدة؛ النسخ المتطابقة لا تُكرر.</p>}
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={() => setEditor(null)}>إلغاء</button><button className="button" disabled={mutationBusy || unchangedNewVersion}>{editor.mode === 'edit-draft' ? 'حفظ المسودة' : 'إنشاء نسخة مسودة'}</button></div>
    </form></div>}
    <ConfirmDialog
      open={Boolean(confirmation)}
      title={confirmation?.action === 'archive' ? 'أرشفة مستند المعرفة؟' : confirmation?.action === 'restore' ? 'استعادة مستند المعرفة؟' : confirmation?.revision.status === 'historical' ? 'إعادة اعتماد نسخة سابقة؟' : 'اعتماد نسخة المعرفة؟'}
      body={confirmation?.action === 'archive' ? 'سيُستبعد المستند فوراً من الاسترجاع مع حفظ جميع النسخ وسجل الاعتماد.' : confirmation?.action === 'restore' ? 'سيُستعاد المستند نفسه وتبقى أرقام النسخ والمعرّفات محفوظة، ثم تبدأ مزامنة FAISS.' : 'ستصبح النسخة المحددة هي النسخة الفعالة الوحيدة، وتبقى بقية النسخ للقراءة التاريخية.'}
      confirmLabel={confirmation?.action === 'archive' ? 'نعم، أرشفه' : confirmation?.action === 'restore' ? 'نعم، استعده' : 'نعم، اعتمد النسخة'}
      danger={confirmation?.action === 'archive'}
      busy={archive.isPending || restore.isPending || approve.isPending}
      onClose={() => setConfirmation(null)}
      onConfirm={confirm}
    />
  </>
}

export function KnowledgeStatusSummary({ detail, selectedRevision }: { detail: KnowledgeDetail; selectedRevision: string | null }) {
  const effective = detail.revisions.find(item => item.effective)
  const selected = detail.revisions.find(item => item.id === selectedRevision)
  return <dl className="knowledge-status-grid">
    <div><dt>حالة المستند</dt><dd>{detail.document.status === 'archived' ? 'مؤرشف' : detail.document.status === 'approved' ? 'نشط' : 'مسودة'}</dd></div>
    <div><dt>النسخة الفعالة</dt><dd>{effective ? `Version ${effective.version}` : 'لا توجد نسخة فعالة'}</dd></div>
    <div><dt>النسخة المحددة</dt><dd>{selected ? `Version ${selected.version}` : '—'}</dd></div>
    <div><dt>حالة النسخة</dt><dd>{selected ? revisionStatusLabel(selected) : '—'}</dd></div>
    <div><dt>متاح للاسترجاع</dt><dd>{detail.retrieval_eligible ? 'متاح للاسترجاع' : 'غير متاح للاسترجاع'}</dd></div>
    <div><dt>حالة مزامنة FAISS</dt><dd>{detail.faiss_sync_status === 'synchronized' ? 'متزامن' : detail.faiss_sync_status === 'building' ? 'جارٍ بناء الفهرس' : 'يحتاج إعادة بناء الفهرس'}</dd></div>
  </dl>
}

function TechnicalValue({ value, copy = false }: { value: string; copy?: boolean }) {
  return <span className="technical-value" dir="ltr"><bdi>{value}</bdi>{copy && <button type="button" className="copy-button" onClick={() => void navigator.clipboard?.writeText(value)}>نسخ</button>}</span>
}
