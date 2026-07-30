import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Language } from '../types'

const messages = {
  ar: {
    overview: 'نظرة عامة', conversations: 'المحادثات', knowledge: 'قاعدة المعرفة', hotelData: 'بيانات الفندق', requests: 'طلبات الخدمة', evaluations: 'التقييمات',
    logout: 'تسجيل الخروج', search: 'بحث', status: 'الحالة', language: 'اللغة', all: 'الكل', loading: 'جارٍ التحميل…', retry: 'إعادة المحاولة',
    noResults: 'لا توجد نتائج مطابقة', previous: 'السابق', next: 'التالي', save: 'حفظ', cancel: 'إلغاء', close: 'إغلاق', details: 'التفاصيل',
  },
  en: {
    overview: 'Overview', conversations: 'Conversations', knowledge: 'Knowledge', hotelData: 'Hotel Data', requests: 'Service requests', evaluations: 'Evaluations',
    logout: 'Sign out', search: 'Search', status: 'Status', language: 'Language', all: 'All', loading: 'Loading…', retry: 'Retry',
    noResults: 'No matching results', previous: 'Previous', next: 'Next', save: 'Save', cancel: 'Cancel', close: 'Close', details: 'Details',
  },
} as const

type MessageKey = keyof typeof messages.en
interface I18nValue { language: Language; setLanguage(value: Language): void; t(key: MessageKey): string }
const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => navigator.language.startsWith('ar') ? 'ar' : 'en')
  useEffect(() => {
    document.documentElement.lang = language
    document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr'
  }, [language])
  const value = useMemo(() => ({ language, setLanguage, t: (key: MessageKey) => messages[language][key] }), [language])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside I18nProvider')
  return value
}
