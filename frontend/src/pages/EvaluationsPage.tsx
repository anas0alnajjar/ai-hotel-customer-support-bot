import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, MetricValue, PageHeader, Pagination, StatusBadge } from '../components/ui'
import { api, queryString } from '../lib/api'
import type { Evaluation, Page } from '../types'

export function EvaluationsPage() {
  const { token } = useAuth(); const client = useQueryClient(); const [page, setPage] = useState(1); const [selected, setSelected] = useState<Evaluation | null>(null)
  const query = useQuery({ queryKey: ['evaluations', page], queryFn: () => api<Page<Evaluation>>(`/admin/evaluations${queryString({ page, page_size: 15 })}`, { token }) })
  const run = useMutation({ mutationFn: () => api<Evaluation>('/admin/evaluations', { method: 'POST', token, body: { dataset_version: 'hotel-support-baseline-v1' } }), onSuccess: async result => { setSelected(result); await client.invalidateQueries({ queryKey: ['evaluations'] }) } })
  return <>
    <PageHeader eyebrow="QUALITY LAB" title="التقييمات" description="شغّل خط التقييم المجمّد وقارن جودة النية والاسترجاع والإجابة والأدوات بإصدارات النظام." action={<button className="button" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'جارٍ التشغيل…' : 'تشغيل تقييم جديد'}</button>} />
    {run.error && <ErrorState error={run.error} />}
    <section className="quality-banner"><div><span className="quality-icon">◎</span><span><strong>Frozen evaluation policy</strong><small>Evaluator labels remain observations—not automatic ground truth.</small></span></div><code>hotel-support-baseline-v1</code></section>
    {query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : !query.data?.items.length ? <EmptyState title="لا توجد تشغيلات بعد" body="ابدأ أول تقييم قابل لإعادة الإنتاج من الزر أعلاه." /> : <section className="evaluation-layout"><div className="panel evaluation-list">{query.data.items.map(item => <button className={selected?.id === item.id ? 'selected' : ''} key={item.id} onClick={() => setSelected(item)}><span><strong>{item.dataset_version}</strong><small>{new Date(item.created_at).toLocaleString()}</small></span><StatusBadge value={item.status} /></button>)}<Pagination page={query.data.page} pages={query.data.pages} onPage={setPage} /></div><EvaluationDetail item={selected ?? query.data.items[0] ?? null} /></section>}
  </>
}

function EvaluationDetail({ item }: { item: Evaluation | null }) {
  if (!item) return null
  const sections = item.metrics ? Object.entries(item.metrics) : []
  return <article className="panel evaluation-detail"><div className="panel-heading"><div><p className="eyebrow">RUN REPORT</p><h2>{item.id.slice(0, 8)}</h2></div><StatusBadge value={item.status} /></div><dl className="version-grid">{Object.entries(item.system_versions).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl>{sections.map(([section, values]) => <section className="metric-section" key={section}><h3>{section.replaceAll('_', ' ')}</h3><div className="metric-grid">{typeof values === 'object' && values !== null ? Object.entries(values as Record<string, unknown>).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><MetricValue value={value} /></div>) : <MetricValue value={values} />}</div></section>)}</article>
}
