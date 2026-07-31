import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, MetricValue, PageHeader, Pagination, StatusBadge } from '../components/ui'
import { api, queryString } from '../lib/api'
import type { Evaluation, Page } from '../types'

const METRIC_EXPLANATIONS: Record<string, { ar: string; en: string; warning?: string }> = {
  accuracy: {
    ar: 'نسبة عينات النية التي تطابقت فيها النتيجة مع التصنيف المتوقع مباشرة.',
    en: 'Share of intent samples whose predicted class exactly matched the expected class.',
  },
  coverage: {
    ar: 'نسبة العينات التي تجاوز فيها المصنف حدّي الثقة والهامش المحددين في تقرير النية.',
    en: 'Share of samples accepted by the classifier confidence and margin thresholds recorded in the intent report.',
  },
  macro_f1: {
    ar: 'متوسط F1 بين جميع فئات النوايا، بحيث تحصل كل فئة على وزن متساوٍ.',
    en: 'Mean F1 across intent classes, with every class weighted equally.',
  },
  recall_at_k: {
    ar: 'متوسط نسبة المستندات الصحيحة التي ظهرت ضمن أول K نتائج، وليس بالضرورة أول نتيجة.',
    en: 'Average share of expected documents found within the first K results, not necessarily at rank one.',
  },
  top_1_accuracy: {
    ar: 'نسبة الأسئلة التي ظهر مستندها الصحيح في المرتبة الأولى تحديداً.',
    en: 'Share of questions whose expected document appeared at rank one.',
  },
  mean_reciprocal_rank: {
    ar: 'متوسط مقلوب ترتيب أول مستند صحيح؛ ترتفع النتيجة كلما ظهر مبكراً.',
    en: 'Mean reciprocal rank of the first relevant document; earlier relevant results score higher.',
  },
  traceability_rate: {
    ar: 'نسبة حالات الاختبار التي أمكن فيها ربط جميع معرّفات النتائج المسترجعة بمستندات مجموعة البيانات.',
    en: 'Share of test cases whose retrieved identifiers all mapped to documents in the evaluation dataset.',
    warning: 'قابلية التتبع لا تعني أن الدليل المختار صحيح. Traceability does not prove that the selected evidence is correct.',
  },
  success_rate: {
    ar: 'نسبة استدعاءات مزود LLM التي نجحت تقنياً من إجمالي الاستدعاءات المسجلة.',
    en: 'Share of recorded LLM provider calls that completed technically successfully.',
    warning: 'نجاح استدعاءات النموذج بنسبة 100% لا يعني أن جميع الإجابات صحيحة. 100% LLM reliability does not mean 100% answer accuracy.',
  },
  valid_request_success_rate: {
    ar: 'نسبة الطلبات القابلة للتنفيذ التي نجحت، مع استبعاد الرفض المتوقع من المقام.',
    en: 'Success rate among executable valid requests; expected rejections are excluded from the denominator.',
  },
}

const TOOL_STATUS_LABELS: Record<string, string> = {
  succeeded: 'ناجح / Succeeded',
  rejected: 'مرفوض بشكل متوقع / Expected rejected',
  failed: 'فشل غير متوقع / Unexpected failed',
  timed_out: 'انتهت المهلة / Timed out',
  in_progress: 'قيد التنفيذ / In progress',
  pending: 'قيد الانتظار / Pending',
}

export function isOfflineTestEmbedding(value: unknown): boolean {
  return typeof value === 'string' && value.startsWith('hashing-test-v1:')
}

export function metricExplanation(key: string) {
  return METRIC_EXPLANATIONS[key]
}

export function toolStatusLabel(status: string): string {
  return TOOL_STATUS_LABELS[status] ?? status.replaceAll('_', ' ')
}

export function EvaluationsPage() {
  const { token } = useAuth()
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Evaluation | null>(null)
  const query = useQuery({
    queryKey: ['evaluations', page],
    queryFn: () => api<Page<Evaluation>>(`/admin/evaluations${queryString({ page, page_size: 15 })}`, { token }),
  })
  const run = useMutation({
    mutationFn: () => api<Evaluation>('/admin/evaluations', { method: 'POST', token, body: { dataset_version: 'hotel-support-baseline-v1' } }),
    onSuccess: async result => { setSelected(result); await client.invalidateQueries({ queryKey: ['evaluations'] }) },
  })
  return <>
    <PageHeader eyebrow="QUALITY LAB" title="التقييمات" description="اقرأ كل تشغيل ضمن نسخته وبياناته ونطاقه؛ التشغيل غير المتصل ليس إثباتاً على الإنتاج الحالي." action={<button className="button" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'جارٍ التشغيل…' : 'تشغيل تقييم Offline'}</button>} />
    {run.error && <ErrorState error={run.error} />}
    <section className="quality-banner"><div><span className="quality-icon">◎</span><span><strong>Frozen evaluation policy / سياسة تقييم مجمّدة</strong><small>Evaluator labels are observations—not automatic ground truth. تقييمات المراجع ملاحظات وليست حقيقة تلقائية.</small></span></div><code dir="ltr">hotel-support-baseline-v1</code></section>
    <HowToReadEvaluations />
    {query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : !query.data?.items.length ? <EmptyState title="لا توجد تشغيلات بعد" body="ابدأ تقييماً غير متصل من الزر أعلاه." /> : <section className="evaluation-layout">
      <div className="panel evaluation-list">{query.data.items.map(item => <button className={(selected?.id ?? query.data.items[0]?.id) === item.id ? 'selected' : ''} key={item.id} onClick={() => setSelected(item)}><span><strong>{String(item.system_versions.run_name ?? item.dataset_version)}</strong><small>{new Date(item.created_at).toLocaleString()} · Offline snapshot</small></span><StatusBadge value={item.status} /></button>)}<Pagination page={query.data.page} pages={query.data.pages} onPage={setPage} /></div>
      <EvaluationDetail item={selected ?? query.data.items[0] ?? null} />
    </section>}
  </>
}

export function EvaluationDetail({ item }: { item: Evaluation | null }) {
  if (!item) return null
  const embeddingModel = item.system_versions.embedding_model
  const metrics = item.metrics ?? {}
  return <article className="panel evaluation-detail">
    <div className="panel-heading evaluation-heading"><div><p className="eyebrow">HISTORICAL RUN RECORD</p><h2>{String(item.system_versions.run_name ?? item.dataset_version)}</h2><p className="run-subtitle">سجل تاريخي/غير متصل — لا يثبت حالة نسخة الإنتاج الحالية.</p></div><StatusBadge value={item.status} /></div>
    <div className="run-badges"><span className="badge badge-warning">Offline</span><span className="badge badge-neutral">Frozen baseline</span>{isOfflineTestEmbedding(embeddingModel) && <span className="badge badge-warning">نموذج تضمين اختباري غير إنتاجي / Offline test embedding model</span>}</div>
    {isOfflineTestEmbedding(embeddingModel) && <div className="inline-alert evaluation-warning">نتائج الاسترجاع هذه لا تمثل أداء نموذج التضمين الإنتاجي. This retrieval result does not represent production Sentence Transformer performance.</div>}
    <RunIdentity item={item} />
    {Object.entries(metrics).map(([section, values]) => <MetricSection key={section} section={section} values={values} />)}
    {item.error_summary && <div className="inline-alert"><strong>خطأ التشغيل:</strong> {item.error_summary}</div>}
  </article>
}

export function HowToReadEvaluations() {
  return <details className="panel evaluation-help" open>
    <summary>كيف أقرأ نتائج التقييم؟ / How to read this evaluation</summary>
    <ol>
      <li>مقاييس Intent تختبر التصنيف والتوجيه. Intent metrics evaluate routing/classification.</li>
      <li>مقاييس Retrieval تختبر ظهور الدليل المتوقع وترتيبه. Retrieval metrics evaluate expected evidence retrieval and ranking.</li>
      <li>جودة الإجابة تحتاج عينات يراجعها بشر. Answer quality requires human evaluator labels.</li>
      <li>مقاييس الأدوات تختبر التنفيذ المضبوط. Tool metrics evaluate controlled operation execution.</li>
      <li>LLM reliability تقيس الحالة التقنية لاتصال المزود، لا صحة المعنى.</li>
      <li>تشغيل Offline لا يساوي تحقق الإنتاج. Offline runs are not production validation.</li>
      <li>ارتفاع Recall@K مع انخفاض Top 1 يعني أن الدليل الصحيح موجود غالباً بين المرشحين لكن ترتيبه أولاً يحتاج تحسيناً.</li>
      <li>التشغيل التاريخي يصف النسخة والبيانات المسجلة فيه، وليس بالضرورة النسخة المنشورة حالياً.</li>
    </ol>
  </details>
}

function RunIdentity({ item }: { item: Evaluation }) {
  const identity: Array<[string, unknown]> = [
    ['run_id', item.id], ['run_name', item.system_versions.run_name ?? item.dataset_version],
    ['created_at', new Date(item.created_at).toLocaleString()], ['status', item.status],
    ['mode', item.system_versions.run_mode ?? 'historical / not recorded'],
    ['baseline', item.system_versions.baseline_type ?? 'historical / not recorded'],
    ...Object.entries(item.system_versions).filter(([key]) => !['run_name', 'run_mode', 'baseline_type'].includes(key)),
  ]
  return <section className="run-identity"><h3>هوية التشغيل / Run identity</h3><dl className="version-grid">{identity.map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><TechnicalValue value={String(value ?? 'not recorded')} copy={isTechnicalKey(key)} /></dd></div>)}</dl></section>
}

function MetricSection({ section, values }: { section: string; values: unknown }) {
  if (section === 'answer_quality') return <AnswerQuality values={asRecord(values)} />
  if (section === 'tool_execution') return <ToolExecutionMetrics values={asRecord(values)} />
  const entries = Object.entries(asRecord(values))
  return <section className="metric-section"><h3>{section.replaceAll('_', ' ')}</h3><div className="metric-grid">{entries.map(([key, value]) => <MetricCard key={key} metricKey={key} value={value} />)}</div></section>
}

function MetricCard({ metricKey, value }: { metricKey: string; value: unknown }) {
  const explanation = metricExplanation(metricKey)
  return <div className="metric-card"><span>{metricKey.replaceAll('_', ' ')}</span>{isPlainRecord(value) ? <ReadableCounts values={value} /> : isTechnicalKey(metricKey) && typeof value === 'string' ? <TechnicalValue value={value} copy /> : <MetricValue value={value} />}{explanation && <p className="metric-help">{explanation.ar}<br /><span lang="en" dir="ltr">{explanation.en}</span>{explanation.warning && <strong>{explanation.warning}</strong>}</p>}</div>
}

function AnswerQuality({ values }: { values: Record<string, unknown> }) {
  const sampleCount = Number(values.evaluator_sample_count ?? 0)
  return <section className="metric-section"><h3>answer quality</h3>{sampleCount === 0 ? <div className="answer-quality-empty"><strong>لا توجد تقييمات بشرية للإجابات حتى الآن. / No human evaluator labels yet.</strong><p>تسميات المراجعين ملاحظات وليست حقيقة تلقائية، ولا يمكن استنتاج جودة الإجابة قبل مراجعة عينات فعلية.</p></div> : <div className="metric-grid">{Object.entries(values).map(([key, value]) => <MetricCard key={key} metricKey={key} value={value} />)}</div>}<p className="metric-section-note">Evaluator labels are observations—not automatic ground truth. تبقى سياسة التقييم المجمّدة ظاهرة ولا تُعد التسميات حقيقة تلقائية.</p></section>
}

function ToolExecutionMetrics({ values }: { values: Record<string, unknown> }) {
  const counts = asRecord(values.status_counts)
  const total = Number(values.sample_count ?? 0)
  const expectedRejected = Number(values.expected_requests_rejected ?? 0)
  return <section className="metric-section"><h3>tool execution</h3><div className="metric-grid">
    <MetricCard metricKey="total_attempts" value={values.sample_count} />
    <MetricCard metricKey="valid_tool_requests_succeeded" value={values.valid_tool_requests_succeeded} />
    <MetricCard metricKey="expected_requests_rejected" value={values.expected_requests_rejected} />
    <MetricCard metricKey="expected_rejection_rate" value={total ? expectedRejected / total : null} />
    <MetricCard metricKey="unexpected_execution_failures" value={values.unexpected_execution_failures} />
    <MetricCard metricKey="valid_request_success_rate" value={values.valid_request_success_rate} />
    <div className="metric-card"><span>status breakdown</span><div className="status-counts">{Object.entries(counts).map(([status, count]) => <span className="badge badge-neutral" key={status}>{toolStatusLabel(status)}: {String(count)}</span>)}</div></div>
  </div><p className="metric-section-note">قد يعني رفض العملية أن قواعد التحقق والأمان عملت كما هو متوقع. A rejected operation may prove that validation and security controls worked correctly.</p></section>
}

function ReadableCounts({ values }: { values: Record<string, unknown> }) {
  return <div className="status-counts">{Object.entries(values).map(([key, value]) => <span className="badge badge-neutral" key={key}>{toolStatusLabel(key)}: {String(value)}</span>)}</div>
}

function TechnicalValue({ value, copy = false }: { value: string; copy?: boolean }) {
  return <span className="technical-value" dir="ltr"><bdi>{value}</bdi>{copy && <button type="button" className="copy-button" onClick={() => void navigator.clipboard?.writeText(value)}>Copy</button>}</span>
}

function asRecord(value: unknown): Record<string, unknown> {
  return isPlainRecord(value) ? value : { value }
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isTechnicalKey(key: string): boolean {
  return /(id|sha|commit|model|classifier|dataset|report|router|application)/.test(key)
}
