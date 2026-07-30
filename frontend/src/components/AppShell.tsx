import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useI18n } from '../i18n/I18nContext'
import type { Role } from '../types'

const nav: { to: string; key: 'overview' | 'conversations' | 'knowledge' | 'hotelData' | 'requests' | 'evaluations'; icon: string; roles: Role[] }[] = [
  { to: '/', key: 'overview', icon: '⌂', roles: ['admin', 'support', 'evaluator'] },
  { to: '/conversations', key: 'conversations', icon: '◫', roles: ['admin', 'support', 'evaluator'] },
  { to: '/knowledge', key: 'knowledge', icon: '▤', roles: ['admin'] },
  { to: '/hotel-data', key: 'hotelData', icon: '▦', roles: ['admin'] },
  { to: '/requests', key: 'requests', icon: '◇', roles: ['admin', 'support'] },
  { to: '/evaluations', key: 'evaluations', icon: '⌁', roles: ['admin', 'evaluator'] },
]

export function AppShell() {
  const { admin, logout } = useAuth()
  const { language, setLanguage, t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!admin) return null
  return <div className="app-shell">
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Primary navigation">
      <div className="brand"><span className="brand-mark">ن</span><div><strong>Nour Al-Sham</strong><small>AI Operations</small></div></div>
      <nav className="nav-list">
        {nav.filter(item => item.roles.includes(admin.role)).map(item => <NavLink key={item.to} to={item.to} end={item.to === '/'} onClick={() => setOpen(false)}><span aria-hidden="true">{item.icon}</span>{t(item.key)}</NavLink>)}
      </nav>
      <div className="sidebar-footer"><span className="live-dot" />Hotel systems console</div>
    </aside>
    {open && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <div className="workspace">
      <header className="topbar">
        <button className="menu-button" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(!open)}>☰</button>
        <div className="topbar-context"><span className="topbar-kicker">Nour Al-Sham Grand Hotel</span><strong>Command Center</strong></div>
        <div className="topbar-actions">
          <button className="language-switch" onClick={() => setLanguage(language === 'ar' ? 'en' : 'ar')} aria-label="Switch language">{language === 'ar' ? 'EN' : 'ع'}</button>
          <div className="profile"><span className="avatar">{admin.username.slice(0, 1).toUpperCase()}</span><div><strong>{admin.username}</strong><small>{admin.role}</small></div></div>
          <button className="button ghost logout" onClick={logout}>{t('logout')}</button>
        </div>
      </header>
      <main id="main-content" className="main-content" tabIndex={-1}><Outlet /></main>
    </div>
  </div>
}
