export type Role = 'admin' | 'support' | 'evaluator'
export type Language = 'ar' | 'en'

export interface AdminPrincipal { id: string; email: string; username: string; role: Role }
export interface LoginResponse { access_token: string; token_type: 'bearer'; expires_in: number; admin: AdminPrincipal }
export interface Page<T> { items: T[]; page: number; page_size: number; total: number; pages: number }

export interface Conversation {
  id: string; guest_reference: string; channel: string; status: string; language: string
  message_count: number; last_message_preview: string | null; latest_intent: string | null
  escalation_status: string | null; started_at: string; last_activity_at: string; closed_at: string | null
}
export interface Message { id: string; sequence_number: number; direction: string; text: string; language: string; intent: string | null; confidence: number | null; classifier_version: string | null; correlation_id: string; created_at: string; redacted: boolean }
export interface ToolEvent { id: string; message_id: string; tool_name: string; arguments: Record<string, unknown>; result_status: string; result: Record<string, unknown> | null; latency_ms: number; correlation_id: string; error_code: string | null; created_at: string }
export interface Feedback { id: string; message_id: string; source: string; rating: number | null; label: string | null; comment: string | null; created_at: string }
export interface Escalation { id: string; reason: string; status: string; assigned_to: string | null; created_at: string; updated_at: string; resolved_at: string | null }
export interface ConversationDetail { conversation: Conversation; messages: Message[]; tool_events: ToolEvent[]; feedback: Feedback[]; escalations: Escalation[] }

export interface Knowledge { id: string; title: string; language: string; source_format: string; status: string; current_revision_id: string | null; revision_count: number; created_at: string; updated_at: string }
export interface KnowledgeRevision { id: string; version: number; content: string; checksum: string; created_by: string | null; created_at: string }
export interface KnowledgeDetail { document: Knowledge; revisions: KnowledgeRevision[] }

export interface ServiceRequest { id: string; tracking_code: string; request_type: string; category: string; room_number: string; description: string; urgency: string; status: string; created_at: string; updated_at: string; completed_at: string | null }
export interface Evaluation { id: string; dataset_version: string; system_versions: Record<string, unknown>; metrics: Record<string, unknown> | null; status: string; started_at: string | null; finished_at: string | null; error_summary: string | null; created_at: string }
export interface Health { status: 'ok' | 'degraded' | 'not_ready'; service: string; version: string; checks: Record<string, string> }

export interface RoomType {
  id: string; code: string; name_ar: string; name_en: string
  capacity_adults: number; capacity_children: number
  nightly_rate_cents: number; currency: string; active: boolean
}
export interface HotelRoom {
  id: string; room_number: string; room_type_id: string; room_type_code: string
  floor: number; operational_status: string
}
export interface Booking {
  id: string; reference: string; guest_name_masked: string
  check_in: string; check_out: string; room_type_id: string
  room_type_code: string; room_id: string | null; room_number: string | null
  adults: number; children: number; status: string
}
export interface BookingMutation {
  booking: Booking; verification_code_once: string | null
}
export interface DemoCredential {
  booking_reference: string; verification_code: string
}
export interface DemoCredentials {
  label: string; dataset_version: string; credentials: DemoCredential[]
}
