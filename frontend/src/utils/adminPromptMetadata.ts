import { i18n } from '@/i18n'

export interface LocalizedPromptMeta {
  name: string
  description?: string | null
}

const translatedOrFallback = (key: string, fallback?: string | null): string => {
  if (!i18n.global.te(key)) return fallback || ''
  return i18n.global.t(key)
}

export const localizePromptFunction = (
  functionKey: string,
  fallbackName: string,
  fallbackDescription?: string | null,
): LocalizedPromptMeta => {
  const key = `admin.prompts.metadata.functions.${functionKey}`
  return {
    name: translatedOrFallback(`${key}.name`, fallbackName),
    description: translatedOrFallback(`${key}.description`, fallbackDescription),
  }
}

export const localizePromptAgent = (
  functionKey: string,
  agentKey: string,
  fallbackName: string,
  fallbackDescription?: string | null,
): LocalizedPromptMeta => {
  const key = `admin.prompts.metadata.agents.${functionKey}.${agentKey}`
  return {
    name: translatedOrFallback(`${key}.name`, fallbackName),
    description: translatedOrFallback(`${key}.description`, fallbackDescription),
  }
}

export const localizeProjectAgent = (
  agentKey: string,
  fallbackName: string,
  fallbackDescription?: string | null,
): LocalizedPromptMeta => {
  const key = `admin.prompts.metadata.projectAgents.${agentKey}`
  return {
    name: translatedOrFallback(`${key}.name`, fallbackName),
    description: translatedOrFallback(`${key}.description`, fallbackDescription),
  }
}

export const localizePromptPreviewLayer = (layerKey: string, fallbackLabel: string): string =>
  translatedOrFallback(`admin.prompts.metadata.previewLayers.${layerKey}`, fallbackLabel)
