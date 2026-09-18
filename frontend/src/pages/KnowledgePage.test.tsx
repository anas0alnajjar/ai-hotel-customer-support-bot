import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { KnowledgeDetail, KnowledgeRevision } from '../types'
import {
  documentLifecycleAction,
  effectiveRevision,
  KnowledgeStatusSummary,
  pendingDraft,
} from './KnowledgePage'

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

describe('Knowledge presentation', () => {
  it('keeps the document lifecycle simple', () => {
    expect(documentLifecycleAction('archived')).toBe('restore')
    expect(documentLifecycleAction('approved')).toBe('archive')
    expect(effectiveRevision(knowledgeDetail)?.id).toBe('rev-1')
    expect(pendingDraft(knowledgeDetail)?.id).toBe('rev-2')
  })

  it('shows only the status needed for the demonstration', () => {
    const html = renderToStaticMarkup(<KnowledgeStatusSummary detail={knowledgeDetail} />)
    expect(html).toContain('حالة المستند')
    expect(html).toContain('متاح عبر RAG')
    expect(html).toContain('متزامن')
    expect(html).not.toContain('SHA')
  })
})
