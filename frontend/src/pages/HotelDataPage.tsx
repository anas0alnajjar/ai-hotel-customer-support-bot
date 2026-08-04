import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { ApiError, api, queryString } from '../lib/api'
import type {
  Booking,
  BookingMutation,
  DemoCredentials,
  HotelRoom,
  RoomType,
} from '../types'

type Tab = 'room-types' | 'rooms' | 'bookings'

export const PRIMARY_HOTEL_DATA_TABS: ReadonlyArray<readonly [Tab, string]> = [
  ['room-types', 'Room Types'],
  ['rooms', 'Rooms'],
  ['bookings', 'Bookings'],
]

const roomStatuses = ['available', 'occupied', 'cleaning', 'maintenance', 'out_of_service']
const bookingStatuses = ['pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled']

async function copy(value: string): Promise<void> {
  await navigator.clipboard.writeText(value)
}

export function HotelDataPage() {
  const [tab, setTab] = useState<Tab>('room-types')
  return <>
    <PageHeader
      eyebrow="SIMULATED HOTEL OPERATIONS"
      title="بيانات الفندق · Hotel Data"
      description="إدارة أنواع الغرف والغرف والحجوزات التي تستخدمها أدوات الفندق المحاكية."
    />
    <nav className="hotel-tabs" aria-label="Hotel data sections">
      {PRIMARY_HOTEL_DATA_TABS.map(([value, label]) => (
        <button
          className={tab === value ? 'active' : ''}
          key={value}
          onClick={() => setTab(value)}
        >{label}</button>
      ))}
    </nav>
    {tab === 'room-types' && <RoomTypesPanel />}
    {tab === 'rooms' && <RoomsPanel />}
    {tab === 'bookings' && <BookingsPanel />}
  </>
}

function RoomTypesPanel() {
  const { token } = useAuth()
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ['hotel-room-types'],
    queryFn: () => api<RoomType[]>('/admin/hotel-data/room-types', { token }),
  })
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api<RoomType>(`/admin/hotel-data/room-types/${id}`, {
        method: 'PATCH', token, body,
      }),
    onSuccess: async () => client.invalidateQueries({ queryKey: ['hotel-room-types'] }),
  })
  if (query.isLoading) return <LoadingState />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  return <section className="panel table-panel">
    {update.error && <ErrorState error={update.error} />}
    <div className="table-wrap"><table>
      <thead><tr><th>Code / Names</th><th>Capacity</th><th>Nightly price</th><th>Active</th><th>Action</th></tr></thead>
      <tbody>{query.data?.map(item => <RoomTypeRow key={item.id} item={item} save={body => update.mutate({ id: item.id, body })} />)}</tbody>
    </table></div>
  </section>
}

function RoomTypeRow({ item, save }: { item: RoomType; save(body: Record<string, unknown>): void }) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    save({
      name_ar: data.get('name_ar'),
      name_en: data.get('name_en'),
      capacity_adults: Number(data.get('capacity_adults')),
      capacity_children: Number(data.get('capacity_children')),
      nightly_rate_cents: Math.round(Number(data.get('price')) * 100),
      active: data.get('active') === 'on',
    })
  }
  return <tr><td>
    <form id={`room-type-${item.id}`} onSubmit={submit} />
    <strong>{item.code}</strong>
    <input form={`room-type-${item.id}`} name="name_ar" defaultValue={item.name_ar} aria-label={`${item.code} Arabic name`} />
    <input form={`room-type-${item.id}`} name="name_en" defaultValue={item.name_en} aria-label={`${item.code} English name`} />
  </td><td><div className="inline-fields">
    <input form={`room-type-${item.id}`} name="capacity_adults" type="number" min="1" max="8" defaultValue={item.capacity_adults} aria-label="Adult capacity" />
    <input form={`room-type-${item.id}`} name="capacity_children" type="number" min="0" max="8" defaultValue={item.capacity_children} aria-label="Child capacity" />
  </div></td><td>
    <input form={`room-type-${item.id}`} name="price" type="number" min="0" step=".01" defaultValue={(item.nightly_rate_cents / 100).toFixed(2)} aria-label="Nightly price" />
    <small>{item.currency}</small>
  </td><td><input form={`room-type-${item.id}`} name="active" type="checkbox" defaultChecked={item.active} aria-label="Active" /></td>
  <td><button form={`room-type-${item.id}`} className="button small">Save</button></td></tr>
}

function RoomsPanel() {
  const { token } = useAuth()
  const client = useQueryClient()
  const [roomType, setRoomType] = useState('')
  const [status, setStatus] = useState('')
  const roomTypes = useQuery({
    queryKey: ['hotel-room-types'],
    queryFn: () => api<RoomType[]>('/admin/hotel-data/room-types', { token }),
  })
  const rooms = useQuery({
    queryKey: ['hotel-rooms', roomType, status],
    queryFn: () => api<HotelRoom[]>(`/admin/hotel-data/rooms${queryString({
      room_type_id: roomType, status,
    })}`, { token }),
  })
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api<HotelRoom>(`/admin/hotel-data/rooms/${id}`, { method: 'PATCH', token, body }),
    onSuccess: async () => client.invalidateQueries({ queryKey: ['hotel-rooms'] }),
  })
  return <>
    <section className="panel filters">
      <select value={roomType} onChange={event => setRoomType(event.target.value)} aria-label="Room type filter">
        <option value="">All room types</option>
        {roomTypes.data?.map(item => <option value={item.id} key={item.id}>{item.code}</option>)}
      </select>
      <select value={status} onChange={event => setStatus(event.target.value)} aria-label="Room status filter">
        <option value="">All statuses</option>
        {roomStatuses.map(value => <option key={value}>{value}</option>)}
      </select>
    </section>
    {update.error && <ErrorState error={update.error} />}
    {rooms.isLoading ? <LoadingState /> : rooms.error ? <ErrorState error={rooms.error} retry={() => void rooms.refetch()} /> :
      <section className="panel table-panel"><div className="table-wrap"><table>
        <thead><tr><th>Room</th><th>Room type</th><th>Floor</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>{rooms.data?.map(item => <tr key={item.id}>
          <td><strong>{item.room_number}</strong><button className="copy-button" onClick={() => void copy(item.room_number)}>Copy</button></td>
          <td><select defaultValue={item.room_type_id} id={`type-${item.id}`}>{roomTypes.data?.map(type => <option value={type.id} key={type.id}>{type.code}</option>)}</select></td>
          <td>{item.floor}</td>
          <td><select defaultValue={item.operational_status} id={`status-${item.id}`}>{roomStatuses.map(value => <option key={value}>{value}</option>)}</select></td>
          <td><button className="button small" onClick={() => update.mutate({
            id: item.id,
            body: {
              room_type_id: (document.getElementById(`type-${item.id}`) as HTMLSelectElement).value,
              operational_status: (document.getElementById(`status-${item.id}`) as HTMLSelectElement).value,
            },
          })}>Save</button></td>
        </tr>)}</tbody>
      </table></div></section>}
  </>
}

function BookingsPanel() {
  const { token } = useAuth()
  const client = useQueryClient()
  const [editing, setEditing] = useState<Booking | null>(null)
  const [oneTimeCode, setOneTimeCode] = useState('')
  const bookings = useQuery({
    queryKey: ['hotel-bookings'],
    queryFn: () => api<Booking[]>('/admin/hotel-data/bookings', { token }),
  })
  const roomTypes = useQuery({
    queryKey: ['hotel-room-types'],
    queryFn: () => api<RoomType[]>('/admin/hotel-data/room-types', { token }),
  })
  const rooms = useQuery({
    queryKey: ['hotel-rooms-all'],
    queryFn: () => api<HotelRoom[]>('/admin/hotel-data/rooms', { token }),
  })
  const save = useMutation({
    mutationFn: ({ id, body }: { id?: string; body: Record<string, unknown> }) =>
      api<BookingMutation>(id ? `/admin/hotel-data/bookings/${id}` : '/admin/hotel-data/bookings', {
        method: id ? 'PATCH' : 'POST', token, body,
      }),
    onSuccess: async result => {
      setOneTimeCode(result.verification_code_once ?? '')
      setEditing(null)
      await client.invalidateQueries({ queryKey: ['hotel-bookings'] })
    },
  })
  const reset = useMutation({
    mutationFn: (id: string) => api<BookingMutation>(`/admin/hotel-data/bookings/${id}/reset-verification`, {
      method: 'POST', token,
    }),
    onSuccess: result => setOneTimeCode(result.verification_code_once ?? ''),
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const body: Record<string, unknown> = {
      guest_name_masked: data.get('guest_name_masked'),
      check_in: data.get('check_in'),
      check_out: data.get('check_out'),
      room_type_id: data.get('room_type_id'),
      room_id: data.get('room_id') || null,
      adults: Number(data.get('adults')),
      children: Number(data.get('children')),
      status: data.get('status'),
    }
    if (!editing) body.reference = data.get('reference')
    const verification = String(data.get('verification_value') ?? '')
    if (verification) body.verification_value = verification
    save.mutate({ id: editing?.id, body })
  }
  const current = editing
  return <>
    {oneTimeCode && <div className="success-banner"><strong>Verification code — shown once:</strong> <code>{oneTimeCode}</code> <button className="copy-button" onClick={() => void copy(oneTimeCode)}>Copy</button></div>}
    {(save.error || reset.error) && <ErrorState error={save.error ?? reset.error} />}
    <section className="panel hotel-editor">
      <div className="panel-heading"><div><p className="eyebrow">{current ? 'EDIT BOOKING' : 'CREATE DEMO BOOKING'}</p><h2>{current?.reference ?? 'New booking'}</h2></div>{current && <button className="button secondary small" onClick={() => setEditing(null)}>Create new</button>}</div>
      <form className="hotel-form" key={current?.id ?? 'new'} onSubmit={submit}>
        <label>Reference<input name="reference" required={!current} disabled={Boolean(current)} defaultValue={current?.reference ?? ''} placeholder="BKG-2026-DEMO01" /></label>
        <label>Masked guest<input name="guest_name_masked" required defaultValue={current?.guest_name_masked ?? ''} placeholder="A*** N***" /></label>
        <label>Check-in<input name="check_in" type="date" required defaultValue={current?.check_in ?? ''} /></label>
        <label>Check-out<input name="check_out" type="date" required defaultValue={current?.check_out ?? ''} /></label>
        <label>Room type<select name="room_type_id" required defaultValue={current?.room_type_id ?? ''}><option value="">Select…</option>{roomTypes.data?.map(item => <option value={item.id} key={item.id}>{item.code}</option>)}</select></label>
        <label>Assigned room<select name="room_id" defaultValue={current?.room_id ?? ''}><option value="">Unassigned</option>{rooms.data?.map(item => <option value={item.id} key={item.id}>{item.room_number} · {item.room_type_code}</option>)}</select></label>
        <label>Adults<input name="adults" type="number" min="1" max="8" required defaultValue={current?.adults ?? 1} /></label>
        <label>Children<input name="children" type="number" min="0" max="8" required defaultValue={current?.children ?? 0} /></label>
        <label>Status<select name="status" defaultValue={current?.status ?? 'confirmed'}>{bookingStatuses.map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Verification code (optional)<input name="verification_value" minLength={4} autoComplete="off" /></label>
        <button className="button" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save booking'}</button>
      </form>
    </section>
    {bookings.isLoading ? <LoadingState /> : bookings.error ? <ErrorState error={bookings.error} retry={() => void bookings.refetch()} /> : !bookings.data?.length ? <EmptyState /> :
      <section className="panel table-panel"><div className="table-wrap"><table>
        <thead><tr><th>Reference / Guest</th><th>Stay</th><th>Room</th><th>Guests</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>{bookings.data.map(item => <tr key={item.id}>
          <td><strong>{item.reference}</strong><small>{item.guest_name_masked}</small><button className="copy-button" onClick={() => void copy(item.reference)}>Copy</button></td>
          <td>{item.check_in}<small>{item.check_out}</small></td>
          <td>{item.room_type_code}<small>{item.room_number ?? 'Unassigned'}</small></td>
          <td>{item.adults} + {item.children}</td><td><StatusBadge value={item.status} /></td>
          <td><div className="action-row"><button className="button secondary small" onClick={() => setEditing(item)}>Edit</button><button className="button secondary small" onClick={() => reset.mutate(item.id)}>Reset code</button></div></td>
        </tr>)}</tbody>
      </table></div></section>}
  </>
}

function DemoPanel() {
  const { token } = useAuth()
  const client = useQueryClient()
  const [confirmation, setConfirmation] = useState('')
  const credentials = useQuery({
    queryKey: ['demo-credentials'],
    queryFn: () => api<DemoCredentials>('/admin/hotel-data/demo-credentials', { token }),
    retry: false,
  })
  const reset = useMutation({
    mutationFn: () => api('/admin/hotel-data/reset', {
      method: 'POST', token, body: { confirmation: 'RESET DEMO DATA' },
    }),
    onSuccess: async () => {
      setConfirmation('')
      await client.invalidateQueries({ queryKey: ['hotel-room-types'] })
      await client.invalidateQueries({ queryKey: ['hotel-rooms'] })
      await client.invalidateQueries({ queryKey: ['hotel-bookings'] })
      await client.invalidateQueries({ queryKey: ['demo-credentials'] })
    },
  })
  if (credentials.isLoading) return <LoadingState />
  if (credentials.error instanceof ApiError && credentials.error.code === 'demo_mode_disabled') {
    return <section className="panel demo-disabled"><h2>Demo mode is disabled</h2><p>Set <code>DEMO_MODE=true</code> only in the protected demonstration environment to enable credentials and reset.</p></section>
  }
  if (credentials.error) return <ErrorState error={credentials.error} />
  return <div className="demo-grid">
    <section className="panel demo-card"><p className="eyebrow">DEMO-ONLY CREDENTIALS</p><h2>{credentials.data?.label}</h2><p>Source: versioned seed manifest · {credentials.data?.dataset_version}</p>
      <div className="credential-list">{credentials.data?.credentials.map(item => <div key={item.booking_reference}><code>{item.booking_reference}</code><code>{item.verification_code}</code><button className="copy-button" onClick={() => void copy(`${item.booking_reference} / ${item.verification_code}`)}>Copy</button></div>)}</div>
    </section>
    <section className="panel demo-card"><p className="eyebrow">TEN-MINUTE SCENARIO</p><h2>Demo scenario</h2><dl className="scenario-list">
      <div><dt>Booking lookup</dt><dd><code>BKG-2026-0001 / 0101</code></dd></div>
      <div><dt>Room service</dt><dd><code>Room 101</code> <button className="copy-button" onClick={() => void copy('101')}>Copy</button></dd></div>
      <div><dt>Maintenance</dt><dd><code>Room 304</code> <button className="copy-button" onClick={() => void copy('304')}>Copy</button></dd></div>
    </dl></section>
    <section className="panel demo-card demo-reset"><p className="eyebrow">PROTECTED RESET</p><h2>Reset demo data</h2><p>Restores deterministic seed-owned rows only. It does not drop MySQL or delete unrelated records.</p>
      {reset.error && <ErrorState error={reset.error} />}
      {reset.isSuccess && <div className="success-banner">Demo data reset completed.</div>}
      <label>Type <code>RESET DEMO DATA</code><input value={confirmation} onChange={event => setConfirmation(event.target.value)} /></label>
      <button className="button danger" disabled={confirmation !== 'RESET DEMO DATA' || reset.isPending} onClick={() => reset.mutate()}>{reset.isPending ? 'Resetting…' : 'Reset demo data'}</button>
    </section>
  </div>
}
