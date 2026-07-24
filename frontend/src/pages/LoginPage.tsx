import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'

export function LoginPage() {
  const { admin, login } = useAuth()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (admin) return <Navigate to="/" replace />
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true)
    try { await login(identifier.trim(), password) }
    catch (cause) { setError(cause instanceof ApiError ? cause.code : 'unexpected_error') }
    finally { setBusy(false) }
  }
  return <main className="login-page">
    <section className="login-visual" aria-label="Hotel operations introduction">
      <div className="login-brand"><span className="brand-mark large">ن</span><span>Nour Al-Sham Grand Hotel</span></div>
      <div className="login-copy"><p className="eyebrow light">AI HOTEL OPERATIONS</p><h1>خدمة استباقية.<br />قرارات أوضح.</h1><p>مساحة تشغيل موحّدة لفريق الفندق: المحادثات، المعرفة، الطلبات، وجودة المساعد الذكي.</p></div>
      <div className="login-proof"><span>MySQL</span><span>Gemini</span><span>FAISS</span><span>Tool Calling</span></div>
    </section>
    <section className="login-panel">
      <form className="login-form" onSubmit={submit}>
        <div><p className="eyebrow">SECURE ADMIN ACCESS</p><h2>تسجيل الدخول</h2><p>استخدم حساب الإدارة المفعّل محلياً.</p></div>
        {error && <div className="inline-alert" role="alert">تعذر تسجيل الدخول: {error}</div>}
        <label>اسم المستخدم أو البريد الإلكتروني<input autoComplete="username" required minLength={3} value={identifier} onChange={event => setIdentifier(event.target.value)} /></label>
        <label>كلمة المرور<input type="password" autoComplete="current-password" required minLength={12} value={password} onChange={event => setPassword(event.target.value)} /></label>
        <button className="button full" disabled={busy}>{busy ? 'جارٍ التحقق…' : 'دخول آمن'}</button>
        <p className="security-note">الجلسة قصيرة الأجل ولا تُحفظ في تخزين المتصفح.</p>
      </form>
    </section>
  </main>
}
