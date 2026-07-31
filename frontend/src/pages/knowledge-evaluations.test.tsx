import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Evaluation, KnowledgeDetail, KnowledgeRevision } from '../types'
import {
  canCreateNewVersion,
  documentLifecycleAction,
  KnowledgeStatusSummary,
  revisionActions,
  revisionStatusLabel,
} from './KnowledgePage'
import {
  EvaluationDetail,
  HowToReadEvaluations,
  isOfflineTestEmbedding,
  metricExplanation,
  toolStatusLabel,
} from './EvaluationsPage'

const approvedRevision: KnowledgeRevision = {
  id: 'rev-1', version: 1, content: 'Approved policy content', checksum: 'a'.repeat(64),
  created_by: 'admin-1', created_at: '2026-07-01T10:00:00Z',
  status: 'approved', approved_at: '2026-07-01T11:00:00Z', approved_by: 'admin-1',
  effective: true, indexed_in_faiss: true, editable: false,
}

describe('Knowledge lifecycle presentation', () => {
  it('shows Restore only for archived parents and Archive for active parents', () => {
    expect(documentLifecycleAction('archived')).toBe('restore')
    expect(documentLifecycleAction('approved')).toBe('archive')
    expect(canCreateNewVersion('archived')).toBe(false)
    expect(canCreateNewVersion('approved')).toBe(true)
  })

  it('keeps approved history read-only and exposes editable draft actions', () => {
    const historical = { ...approvedRevision, id: 'rev-old', status: 'historical' as const, effective: false, indexed_in_faiss: false }
    const draft = { ...approvedRevision, id: 'rev-2', version: 2, status: 'draft' as const, approved_at: null, approved_by: null, effective: false, indexed_in_faiss: false, editable: true }
    expect(revisionActions(historical)).toEqual(['reactivate'])
    expect(revisionStatusLabel(historical)).toContain('تاريخية')
    expect(revisionActions(draft)).toEqual(['edit', 'approve'])
    expect(revisionStatusLabel(draft)).toBe('مسودة')
  })

  it('renders document and revision status, retrieval eligibility, and FAISS state separately', () => {
    const detail: KnowledgeDetail = {
      document: {
        id: 'doc-1', title: 'Policy', language: 'ar', source_format: 'plain_text',
        status: 'archived', current_revision_id: approvedRevision.id, revision_count: 1,
        created_at: '2026-07-01T10:00:00Z', updated_at: '2026-07-02T10:00:00Z',
      },
      revisions: [approvedRevision], retrieval_eligible: false,
      faiss_sync_status: 'needs_rebuild', active_index_id: 'index-1',
    }
    const html = renderToStaticMarkup(<KnowledgeStatusSummary detail={detail} selectedRevision={approvedRevision.id} />)
    expect(html).toContain('حالة المستند')
    expect(html).toContain('مؤرشف')
    expect(html).toContain('حالة النسخة')
    expect(html).toContain('Version 1')
    expect(html).toContain('غير متاح للاسترجاع')
    expect(html).toContain('يحتاج إعادة بناء الفهرس')
  })
})

describe('Evaluation meaning and honesty', () => {
  const evaluation: Evaluation = {
    id: 'evaluation-run-1234567890', dataset_version: 'hotel-support-baseline-v1',
    system_versions: {
      run_name: 'Frozen offline hotel-support baseline', run_mode: 'offline',
      baseline_type: 'frozen_baseline', application: '0.1.0',
      git_commit: '851de5419ca66759d56b6dce91bd2f8906265a7b',
      router: 'hybrid-intent-v1.0.0', intent_classifier: 'classifier-with-a-very-long-version-name',
      intent_dataset: 'intent-dataset-v1.0.0', retrieval_dataset: 'nour-al-sham-knowledge-v1.0.0',
      embedding_model: 'hashing-test-v1:384', llm_model: 'gemini-2.5-flash', llm_called: false,
      intent_sample_count: 80, retrieval_sample_count: 44, evaluator_sample_count: 0,
    },
    metrics: {
      retrieval: { recall_at_k: 0.977, top_1_accuracy: 0.841, traceability_rate: 1 },
      answer_quality: { evaluator_sample_count: 0, average_evaluator_rating: null },
      llm_reliability: { sample_count: 4, success_rate: 1, status_counts: { succeeded: 4 } },
      tool_execution: {
        status_counts: { succeeded: 8, rejected: 6 }, sample_count: 14,
        valid_tool_requests_succeeded: 8, expected_requests_rejected: 6,
        unexpected_execution_failures: 0, valid_request_success_rate: 1,
      },
    },
    status: 'completed', started_at: '2026-07-01T10:00:00Z',
    finished_at: '2026-07-01T10:01:00Z', error_summary: null,
    created_at: '2026-07-01T10:00:00Z',
  }

  it('uses exact metric guidance and readable tool labels', () => {
    expect(metricExplanation('coverage')?.en).toContain('confidence and margin thresholds')
    expect(metricExplanation('traceability_rate')?.warning).toContain('does not prove')
    expect(metricExplanation('success_rate')?.warning).toContain('does not mean 100% answer accuracy')
    expect(toolStatusLabel('rejected')).toContain('مرفوض بشكل متوقع')
  })

  it('marks test embeddings and historical offline runs without raw tool JSON', () => {
    expect(isOfflineTestEmbedding('hashing-test-v1:384')).toBe(true)
    const html = renderToStaticMarkup(<EvaluationDetail item={evaluation} />)
    expect(html).toContain('نموذج تضمين اختباري غير إنتاجي')
    expect(html).toContain('لا توجد تقييمات بشرية للإجابات حتى الآن')
    expect(html).toContain('مرفوض بشكل متوقع')
    expect(html).not.toContain('{&quot;rejected&quot;')
    expect(html).toContain('لا يثبت حالة نسخة الإنتاج الحالية')
    expect(html).toContain('Copy')
  })

  it('keeps the how-to-read panel visible and accessible', () => {
    const html = renderToStaticMarkup(<HowToReadEvaluations />)
    expect(html).toContain('كيف أقرأ نتائج التقييم؟')
    expect(html).toContain('Recall@K')
    expect(html).toContain('Offline runs are not production validation')
  })
})
