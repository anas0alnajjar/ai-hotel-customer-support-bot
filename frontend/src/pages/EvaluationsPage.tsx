import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import type { Evaluation, Page } from '../types'

const METRIC_EXPLANATIONS: Record<string, string> = {
  accuracy: 'نسبة رسائل الاختبار التي طابقت فيها النية النتيجة المتوقعة.',
  recall_at_k: 'نسبة الأسئلة التي ظهر دليلها الصحيح ضمن أول K نتائج.',
  top_1_accuracy: 'نسبة الأسئلة التي ظهر دليلها الصحيح في المرتبة الأولى.',
  valid_request_success_rate: 'نجاح طلبات الأدوات القابلة للتنفيذ بعد استبعاد الرفض المتوقع.',
  unexpected_execution_failures: 'عمليات الأدوات التي فشلت بصورة غير متوقعة.',
  success_rate: 'توفر مزود LLM تقنياً، وليس دقة الإجابة لغوياً أو معرفياً.',
}

export function isOfflineTestEmbedding(value: unknown): boolean {
  return typeof value === 'string' && value.startsWith('hashing-test-v1:')
}

export function metricExplanation(key: string): string | undefined {
  return METRIC_EXPLANATIONS[key]
}

export function EvaluationsPage() {
  const { token } = useAuth()
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ['evaluations', 'submission-summary'],
    queryFn: () => api<Page<Evaluation>>('/admin/evaluations?page=1&page_size=1', { token }),
  })
  const run = useMutation({
    mutationFn: () => api<Evaluation>('/admin/evaluations', {
      method: 'POST', token, body: { dataset_version: 'hotel-support-baseline-v1' },
    }),
    onSuccess: async () => client.invalidateQueries({ queryKey: ['evaluations'] }),
  })
  const latest = query.data?.items[0] ?? null
  return <>
    <PageHeader
      eyebrow="BASIC EVALUATION"
      title="ملخص التقييم"
      description="مؤشرات أساسية لفهم أداء تصنيف النية والاسترجاع والأدوات وتوفر النموذج."
      action={<button className="button" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'جارٍ التشغيل…' : 'تشغيل تقييم Offline'}</button>}
    />
    <EvaluationDisclaimer />
    {run.error && <ErrorState error={run.error} />}
    {query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : !latest ? <EmptyState title="لا يوجد تقييم مسجل" body="يمكن تشغيل التقييم الأساسي دون الاتصال بخدمة Gemini." /> : <EvaluationSummary item={latest} />}
  </>
}

export function EvaluationDisclaimer() {
  return <div className="inline-alert evaluation-disclaimer">Offline evaluation does not automatically prove current production performance.<br />التقييم غير المتصل لا يثبت تلقائياً أداء نسخة الإنتاج الحالية.</div>
}

export function EvaluationSummary({ item }: { item: Evaluation }) {
  const metrics = asRecord(item.metrics)
  const intent = asRecord(metrics.intent)
  const retrieval = asRecord(metrics.retrieval)
  const tools = asRecord(metrics.tool_execution)
  const llm = asRecord(metrics.llm_reliability)
  const mode = String(item.system_versions.run_mode ?? 'historical')
  const embedding = String(item.system_versions.embedding_model ?? 'not recorded')
  return <section className="panel simplified-evaluation">
    <header className="panel-heading evaluation-heading">
      <div><p className="eyebrow">LATEST RECORDED RUN</p><h2>{String(item.system_versions.run_name ?? item.dataset_version)}</h2><p className="run-subtitle">{new Date(item.created_at).toLocaleString()}</p></div>
      <StatusBadge value={item.status} />
    </header>
    <div className="evaluation-context-grid">
      <div><span>Run mode</span><strong>{mode === 'offline' ? 'Offline / غير متصل' : `${mode} / Live`}</strong></div>
      <div><span>Embedding model type</span><strong>{isOfflineTestEmbedding(embedding) ? 'Offline test embedding / نموذج اختباري' : 'Configured production embedding'}</strong><small dir="ltr">{embedding}</small></div>
    </div>
    {isOfflineTestEmbedding(embedding) && <div className="quality-note">نتائج الاسترجاع هنا لا تمثل أداء نموذج Sentence Transformer الإنتاجي.</div>}
    <div className="submission-metric-grid">
      <SimpleMetric label="Intent Accuracy" metricKey="accuracy" value={intent.accuracy} percent />
      <SimpleMetric label="Recall@K" metricKey="recall_at_k" value={retrieval.recall_at_k} percent />
      <SimpleMetric label="Top 1 Accuracy" metricKey="top_1_accuracy" value={retrieval.top_1_accuracy} percent />
      <SimpleMetric label="Valid Tool Success" metricKey="valid_request_success_rate" value={tools.valid_request_success_rate} percent />
      <SimpleMetric label="Unexpected Tool Failures" metricKey="unexpected_execution_failures" value={tools.unexpected_execution_failures} />
      <SimpleMetric label="LLM Technical Availability" metricKey="success_rate" value={llm.success_rate} percent />
    </div>
    <p className="evaluation-footer-note">يعرض هذا الملخص آخر تشغيل مسجل فقط. نجاح LLM تقنياً لا يعني صحة كل إجابة، والرفض المتوقع للأداة لا يُعد فشلاً.</p>
  </section>
}

function SimpleMetric({ label, metricKey, value, percent = false }: { label: string; metricKey: string; value: unknown; percent?: boolean }) {
  const rendered = typeof value === 'number'
    ? percent ? `${(value * 100).toFixed(1)}%` : value.toLocaleString()
    : '—'
  return <article className="submission-metric-card">
    <span>{label}</span><strong>{rendered}</strong><p>{metricExplanation(metricKey)}</p>
  </article>
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}
