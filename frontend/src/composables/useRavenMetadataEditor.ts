import { computed, ref, watch, type Ref } from 'vue'
import { updateRavenPackageMetadata } from '@/api/raven'
import type { RavenComponent, RavenPackage } from '@/types'

type Translate = (key: string, named?: Record<string, unknown>) => string

export interface RavenMetadataEditorOptions {
  /** The package being viewed; edits read from and write back through it. */
  pkg: Ref<RavenPackage | null>
  /** Apply the package returned by the PATCH (carry presentation flags). */
  onSaved: (saved: RavenPackage) => void
  onSuccess: (message: string) => void
  onError: (message: string) => void
  onWarn: (message: string) => void
  t: Translate
}

const normalizeTags = (value?: unknown): string[] => {
  if (!value) return []
  if (Array.isArray(value)) return value.map((tag) => String(tag)).filter(Boolean)
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return parsed.map((tag) => String(tag)).filter(Boolean)
    } catch {
      return value
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean)
    }
  }
  return []
}

export const normalizeComponents = (value?: unknown): RavenComponent[] => {
  if (!value) return []
  let components: any[] = []
  if (Array.isArray(value)) {
    components = value
  } else if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) components = parsed
    } catch {
      components = []
    }
  }

  return components
    .map((item) => {
      if (typeof item === 'string') return { name: item }
      if (item && typeof item === 'object') {
        const name = (item as any).name
        const version = (item as any).version
        if (!name) return null
        return version ? { name: String(name), version: String(version) } : { name: String(name) }
      }
      return null
    })
    .filter(Boolean) as RavenComponent[]
}

/**
 * Description, tag and component editing for the Raven package detail page.
 *
 * Holds draft state for each editable section, saves through the metadata
 * PATCH API, and keeps the draft intact on failure so the user can retry or
 * cancel. Notifications are injected so the composable stays free of any DOM
 * dependency and remains unit-testable.
 */
export function useRavenMetadataEditor(opts: RavenMetadataEditorOptions) {
  const { pkg, onSaved, onSuccess, onError, onWarn, t } = opts

  const canEdit = computed(() => Boolean(pkg.value?.canEditMetadata))
  const currentTags = computed(() => normalizeTags(pkg.value?.metadata?.tags))

  const extractError = (error: any): string =>
    error?.response?.data?.detail || error?.message || t('raven.metadataSaveFail')

  const apply = (saved: RavenPackage) => {
    // The PATCH response omits `canEditMetadata` (only the detail GET adds it);
    // carry the prior flag so edit controls stay visible after a save.
    onSaved({ ...saved, canEditMetadata: pkg.value?.canEditMetadata })
  }

  // ── Description ──
  const editingDesc = ref(false)
  const descDraft = ref('')
  const savingDesc = ref(false)

  const startEditDesc = () => {
    descDraft.value = pkg.value?.metadata?.description || ''
    editingDesc.value = true
  }
  const cancelEditDesc = () => {
    editingDesc.value = false
  }
  const saveDesc = async () => {
    if (!pkg.value) return
    savingDesc.value = true
    try {
      const { data } = await updateRavenPackageMetadata(pkg.value.id, {
        description: descDraft.value,
      })
      if (data?.success && data.data) {
        apply(data.data)
        editingDesc.value = false
        onSuccess(t('raven.descSaveSuccess'))
      } else {
        throw new Error(data?.message || t('raven.metadataSaveFail'))
      }
    } catch (error: any) {
      onError(extractError(error))
    } finally {
      savingDesc.value = false
    }
  }

  // ── Tags ──
  const editingTags = ref(false)
  const tagsDraft = ref<string[]>([])
  const tagInput = ref('')
  const savingTags = ref(false)

  const startEditTags = () => {
    tagsDraft.value = [...currentTags.value]
    tagInput.value = ''
    editingTags.value = true
  }
  const cancelEditTags = () => {
    editingTags.value = false
  }
  const addTag = () => {
    const value = tagInput.value.trim()
    if (!value) return
    if (tagsDraft.value.includes(value)) {
      onWarn(t('raven.tagDuplicate'))
      return
    }
    tagsDraft.value.push(value)
    tagInput.value = ''
  }
  const removeTag = (tag: string) => {
    tagsDraft.value = tagsDraft.value.filter((item) => item !== tag)
  }
  const saveTags = async () => {
    if (!pkg.value) return
    savingTags.value = true
    try {
      const { data } = await updateRavenPackageMetadata(pkg.value.id, {
        tags: tagsDraft.value,
      })
      if (data?.success && data.data) {
        apply(data.data)
        editingTags.value = false
        onSuccess(t('raven.tagsSaveSuccess'))
      } else {
        throw new Error(data?.message || t('raven.metadataSaveFail'))
      }
    } catch (error: any) {
      onError(extractError(error))
    } finally {
      savingTags.value = false
    }
  }

  // 组件草稿与持久化数据分离，取消时不影响详情。
  const editingComponents = ref(false)
  const componentsDraft = ref<RavenComponent[]>([])
  const savingComponents = ref(false)
  let componentGeneration = 0
  watch(() => pkg.value?.id, () => {
    componentGeneration++
    editingComponents.value = false
    componentsDraft.value = []
    savingComponents.value = false
  }, { flush: 'sync' })

  const startEditComponents = () => {
    if (!canEdit.value) return
    componentsDraft.value = normalizeComponents(pkg.value?.metadata?.components)
    editingComponents.value = true
  }
  const cancelEditComponents = () => { editingComponents.value = false }
  const addComponent = () => { componentsDraft.value.push({ name: '', version: '' }) }
  const removeComponent = (index: number) => { componentsDraft.value.splice(index, 1) }
  const saveComponents = async () => {
    if (!pkg.value || !canEdit.value || savingComponents.value) return
    const draft = componentsDraft.value.map(item => ({ name: item.name.trim(), version: (item.version || '').trim() }))
    if (draft.some(item => !item.name)) {
      onWarn(t('raven.componentNameRequired'))
      return
    }
    const generation = componentGeneration
    savingComponents.value = true
    try {
      const { data } = await updateRavenPackageMetadata(pkg.value.id, { components: draft })
      if (generation !== componentGeneration) return
      if (!data?.success || !data.data) throw new Error(data?.message || t('raven.metadataSaveFail'))
      apply(data.data)
      editingComponents.value = false
      onSuccess(t('raven.componentsSaveSuccess'))
    } catch (error: any) {
      if (generation === componentGeneration) onError(extractError(error))
    } finally {
      if (generation === componentGeneration) savingComponents.value = false
    }
  }

  return {
    canEdit,
    editingComponents, componentsDraft, savingComponents,
    startEditComponents, cancelEditComponents, addComponent, removeComponent, saveComponents,
    currentTags,
    // description
    editingDesc,
    descDraft,
    savingDesc,
    startEditDesc,
    cancelEditDesc,
    saveDesc,
    // tags
    editingTags,
    tagsDraft,
    tagInput,
    savingTags,
    startEditTags,
    cancelEditTags,
    addTag,
    removeTag,
    saveTags,
  }
}
