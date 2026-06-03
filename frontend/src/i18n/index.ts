// Frontend i18n entry point.
//
// Single source of truth for the configured `vue-i18n` instance, the Element
// Plus locale packs, and the locale-switch helper. DOM-free primitives (the
// supported-locale list, constants, `getActiveLocale`, normalization) live in
// `./runtime` so the axios layer can import them without pulling in vue-i18n.

import { createI18n } from 'vue-i18n'
import elementZhCn from 'element-plus/es/locale/lang/zh-cn'
import elementEn from 'element-plus/es/locale/lang/en'
import type { Language as ElementLanguage } from 'element-plus/es/locale'

import zh from './zh'
import en from './en'
import {
  DEFAULT_LOCALE,
  getActiveLocale,
  initialLocale,
  setActiveLocale,
  type AppLocale,
} from './runtime'

export * from './runtime'

const datetimeFormats = {
  zh: {
    short: { year: 'numeric', month: '2-digit', day: '2-digit' },
    long: {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    },
  },
  en: {
    short: { year: 'numeric', month: 'short', day: 'numeric' },
    long: {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    },
  },
} as const

const numberFormats = {
  zh: {
    decimal: { style: 'decimal', minimumFractionDigits: 0, maximumFractionDigits: 2 },
    percent: { style: 'percent', maximumFractionDigits: 1 },
  },
  en: {
    decimal: { style: 'decimal', minimumFractionDigits: 0, maximumFractionDigits: 2 },
    percent: { style: 'percent', maximumFractionDigits: 1 },
  },
} as const

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: initialLocale,
  fallbackLocale: DEFAULT_LOCALE,
  messages: { zh, en },
  datetimeFormats: datetimeFormats as any,
  numberFormats: numberFormats as any,
})

const elementLocales: Record<AppLocale, ElementLanguage> = {
  zh: elementZhCn,
  en: elementEn,
}

/** Element Plus locale pack for the given (or active) locale. */
export function getElementLocale(locale?: AppLocale): ElementLanguage {
  return elementLocales[locale ?? getActiveLocale()]
}

/**
 * Set the active locale across vue-i18n + the runtime mirror + localStorage.
 * Does NOT touch the user profile — callers that need to PATCH the profile do so
 * explicitly (see the app store `setLocale`).
 */
export function setI18nLocale(locale: string | null | undefined): AppLocale {
  const next = setActiveLocale(locale)
  i18n.global.locale.value = next
  return next
}

// Ensure the document lang reflects the boot locale.
setI18nLocale(initialLocale)
