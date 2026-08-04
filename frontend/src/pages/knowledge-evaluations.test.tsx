import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Evaluation, KnowledgeDetail, KnowledgeRevision } from '../types'
import {
  documentLifecycleAction,
  effectiveRevision,
  KnowledgeStatusSummary,
  pendingDraft,
} from './KnowledgePage'
import {
  EvaluationDisclaimer,
  EvaluationSummary,
  isOfflineTestEmbedding,
  metricExplanation,
} from './EvaluationsPage'
import { PRIMARY_HOTEL_DATA_TABS } from './HotelDataPage'

const approvedRevision: KnowledgeRevision = {
  id: 'rev-1', version: 1, content: 'Approved policy content', checksum: 'a'.repeat(64),
  created_by: 'admin-1', created_at: '2026-07-01T10:00:00Z',
  status: 'approved', approved_at: '2026-07-01T11:00:00Z', approved_by: 'admin-1',
  effective: true, indexed_in_faiss: true, editable: false,
}

const draftRevision: KnowledgeRevision = {
  ...approvedRevision,
  id: 'rev-2',
  version: 2,
  content: 'Draft policy content',
  status: 'draft',
  approved_at: null,
  approved_by: null,
  effective: false,
  indexed_in_faiss: false,
  editable: true,
}

const knowledgeDetail: KnowledgeDetail = {
  document: {
    id: 'doc-1', title: 'Policy', language: 'ar', source_format: 'plain_text',
    status: 'approved', current_revision_id: approvedRevision.id, revision_count: 2,
    created_at: '2026-07-01T10:00:00Z', updated_at: '2026-07-02T10:00:00Z',
  },
  revisions: [draftRevision, approvedRevision],
  retrieval_eligible: true,
  faiss_sync_status: 'synchronized',
  active_index_id: 'index-1',
}

describe('Simplified Knowledge presentation', () => {
  it('keeps archive/restore and identifies only effective content plus a pending draft', () => {
    expect(documentLifecycleAction('archived')).toBe('restore')
    expect(documentLifecycleAction('approved')).toBe('archive')
    expect(effectiveRevision(knowledgeDetail)?.id).toBe('rev-1')
    expect(pendingDraft(knowledgeDetail)?.id).toBe('rev-2')
  })

  it('shows only submission-level status without SHA or historical reactivation details', () => {
    const html = renderToStaticMarkup(<KnowledgeStatusSummary detail={knowledgeDetail} />)
    expect(html).toContain('حالة المستند')
    expect(html).toContain('Version 1')
    expect(html).toContain('متاح عبر RAG')
    expect(html).toContain('متزامن')
    expect(html).not.toContain('SHA')
    expect(html).not.toContain('اعتماد هذه النسخة')
  })
})

describe('Simplified Evaluation presentation', () => {
  const evaluation: Evaluation = {
    id: 'evaluation-run-1234567890', dataset_version: 'hotel-support-baseline-v1',
    system_versions: {
      run_name: 'Frozen offline hotel-support baseline', run_mode: 'offline',
      embedding_model: 'hashing-test-v1:384',
      git_commit: 'should-not-be-visible-in-summary',
    },
    metrics: {
      intent: { accuracy: 0.875 },
      retrieval: { recall_at_k: 0.977, top_1_accuracy: 0.841 },
      llm_reliability: { success_rate: 1 },
      tool_execution: {
        valid_request_success_rate: 1,
        unexpected_execution_failures: 0,
        status_counts: { succeeded: 8, rejected: 6 },
      },
    },
    status: 'completed', started_at: '2026-07-01T10:00:00Z',
    finished_at: '2026-07-01T10:01:00Z', error_summary: null,
    created_at: '2026-07-01T10:00:00Z',
  }

  it('renders only the six approved summary metrics and run context', () => {
    const html = renderToStaticMarkup(<EvaluationSummary item={evaluation} />)
    expect(html).toContain('Intent Accuracy')
    expect(html).toContain('Recall@K')
    expect(html).toContain('Top 1 Accuracy')
    expect(html).toContain('Valid Tool Success')
    expect(html).toContain('Unexpected Tool Failures')
    expect(html).toContain('LLM Technical Availability')
    expect(html).toContain('Offline test embedding')
    expect(html).not.toContain('should-not-be-visible-in-summary')
    expect(html).not.toContain('status_counts')
  })

  it('keeps the honest offline disclaimer and short metric definitions', () => {
    expect(isOfflineTestEmbedding('hashing-test-v1:384')).toBe(true)
    expect(metricExplanation('recall_at_k')).toContain('أول K')
    const html = renderToStaticMarkup(<EvaluationDisclaimer />)
    expect(html).toContain('does not automatically prove current production performance')
  })

  it('keeps only Room Types, Rooms, and Bookings in primary Hotel Data tabs', () => {
    expect(PRIMARY_HOTEL_DATA_TABS.map(([, label]) => label)).toEqual([
      'Room Types', 'Rooms', 'Bookings',
    ])
  })
})
