// DOM-free locale primitives.
//
// Kept separate from `index.ts` so non-UI layers (the axios API client) can read
// the active locale and constants without importing `vue-i18n`/Element Plus,
// which pull in `@vue/runtime-dom` and require a DOM at module load. `index.ts`
// builds on these primitives and owns the vue-i18n/Element Plus wiring.

export const SUPPORTED_LOCALES = ['zh', 'en'] as const
export type AppLocale = (typeof SUPPORTED_LOCALES)[number]

export const DEFAULT_LOCALE: AppLocale = 'zh'

// Header the API client sends so the backend can resolve the active locale.
export const LOCALE_HEADER = 'X-App-Locale'

// localStorage key for the anonymous/persisted preference.
export const LOCALE_STORAGE_KEY = 'raven_locale'

/** Coerce an arbitrary locale code (e.g. `en-US`, `ZH_CN`) to a supported one. */
export function normalizeLocale(code?: string | null): AppLocale {
  if (!code || typeof code !== 'string') return DEFAULT_LOCALE
  const primary = code.trim().toLowerCase().replace(/_/g, '-').split('-', 1)[0]
  if ((SUPPORTED_LOCALES as readonly string[]).includes(primary)) {
    return primary as AppLocale
  }
  if (primary.startsWith('en')) return 'en'
  if (primary.startsWith('zh')) return 'zh'
  return DEFAULT_LOCALE
}

/** Detect a preferred locale from the browser (`en*` → `en`, otherwise `zh`). */
export function detectBrowserLocale(): AppLocale {
  if (typeof navigator === 'undefined') return DEFAULT_LOCALE
  const candidates = [navigator.language, ...(navigator.languages || [])]
  for (const candidate of candidates) {
    if (candidate && /^en/i.test(candidate)) return 'en'
    if (candidate && /^zh/i.test(candidate)) return 'zh'
  }
  return DEFAULT_LOCALE
}

function readStoredLocale(): AppLocale | null {
  if (typeof window === 'undefined') return null
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY)
    return stored ? normalizeLocale(stored) : null
  } catch {
    return null
  }
}

/** Locale to boot with before the store/profile resolution runs. */
export const initialLocale: AppLocale = readStoredLocale() ?? detectBrowserLocale()

// In-memory mirror of the active locale so non-reactive callers (the api
// client's request interceptor) can read it cheaply without a store import.
let activeLocale: AppLocale = initialLocale

/** Current active locale for non-reactive consumers (e.g. axios interceptors). */
export function getActiveLocale(): AppLocale {
  return activeLocale
}

/**
 * Persist the active locale to the in-memory mirror, localStorage, and the
 * document `lang` attribute. Does NOT touch vue-i18n/Element Plus (that lives in
 * `index.ts` via `setI18nLocale`). Returns the normalized code.
 */
export function setActiveLocale(locale: string | null | undefined): AppLocale {
  const next = normalizeLocale(locale)
  activeLocale = next
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('lang', next === 'zh' ? 'zh-CN' : 'en')
  }
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next)
    }
  } catch {
    // ignore storage failures (private mode, quota, etc.)
  }
  return next
}
