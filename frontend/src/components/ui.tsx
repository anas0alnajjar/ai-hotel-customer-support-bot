import type { ReactNode } from 'react'
import { ApiError } from '../lib/api'
import { useI18n } from '../i18n/I18nContext'

export function StatusBadge({ value }: { value: string | null }) {
  const normalized = value ?? 'none'
  const positive = ['ok', 'active', 'completed', 'resolved', 'succeeded', 'approved', 'configured', 'closed'].includes(normalized)
  const warning = ['degraded', 'pending', 'open', 'in_progress', 'building', 'escalated'].includes(normalized)
  return <span className={`badge ${positive ? 'badge-positive' : warning ? 'badge-warning' : 'badge-neutral'}`}>{normalized.replaceAll('_', ' ')}</span>
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: ReactNode }) {
  return <header className="page-header">
    <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1><p>{description}</p></div>
    {action && <div className="page-action">{action}</div>}
  </header>
}

export function LoadingState() {
  const { t } = useI18n()
  return <div className="state-card" role="status"><span className="spinner" aria-hidden="true" />{t('loading')}</div>
}

export function EmptyState({ title, body }: { title?: string; body?: string }) {
  const { t } = useI18n()
  return <div className="state-card empty"><span className="empty-mark" aria-hidden="true">◇</span><strong>{title ?? t('noResults')}</strong>{body && <p>{body}</p>}</div>
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const { t } = useI18n()
  const apiError = error instanceof ApiError ? error : null
  return <div className="state-card error" role="alert">
    <strong>تعذر إكمال الطلب / Request failed</strong>
    <p>{apiError?.code ?? 'unexpected_error'}</p>
    {apiError?.correlationId && <code>Correlation: {apiError.correlationId}</code>}
    {retry && <button className="button secondary" onClick={retry}>{t('retry')}</button>}
  </div>
}

export function Pagination({ page, pages, onPage }: { page: number; pages: number; onPage(page: number): void }) {
  const { t } = useI18n()
  if (pages <= 1) return null
  return <nav className="pagination" aria-label="Pagination">
    <button className="button secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>{t('previous')}</button>
    <span>{page} / {pages}</span>
    <button className="button secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>{t('next')}</button>
  </nav>
}

export function ConfirmDialog({ open, title, body, confirmLabel, danger = false, busy = false, onConfirm, onClose }: { open: boolean; title: string; body: string; confirmLabel: string; danger?: boolean; busy?: boolean; onConfirm(): void; onClose(): void }) {
  if (!open) return null
  return <div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <section className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
      <h2 id="confirm-title">{title}</h2><p>{body}</p>
      <div className="dialog-actions"><button className="button secondary" onClick={onClose} disabled={busy}>إلغاء / Cancel</button><button autoFocus className={`button ${danger ? 'danger' : ''}`} onClick={onConfirm} disabled={busy}>{busy ? '…' : confirmLabel}</button></div>
    </section>
  </div>
}

export function MetricValue({ value }: { value: unknown }) {
  if (typeof value === 'number') return <strong>{value <= 1 ? `${(value * 100).toFixed(1)}%` : value.toLocaleString()}</strong>
  if (value === null || value === undefined) return <span>—</span>
  if (typeof value === 'string' || typeof value === 'boolean') return <strong>{String(value)}</strong>
  return <code className="json-value">{JSON.stringify(value)}</code>
}
