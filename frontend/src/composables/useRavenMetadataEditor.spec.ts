import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { RavenPackage } from '@/types'

const updateMock = vi.fn()
vi.mock('@/api/raven', () => ({
  updateRavenPackageMetadata: (...args: unknown[]) => updateMock(...args),
}))

import { normalizeComponents, useRavenMetadataEditor } from './useRavenMetadataEditor'

const t = (key: string) => key

const makePkg = (over: Partial<RavenPackage> = {}): RavenPackage => ({
  id: 'pkg-1',
  name: 'pkg-1.tgz',
  version: '1.0.0',
  projectCode: 'alpha',
  size: 11,
  createdAt: '2025-01-01T00:00:00Z',
  metadata: { description: 'original', tags: ['orig'] },
  canEditMetadata: true,
  ...over,
})

const harness = (pkgValue: RavenPackage | null) => {
  const pkg = ref<RavenPackage | null>(pkgValue)
  const onSuccess = vi.fn()
  const onError = vi.fn()
  const onWarn = vi.fn()
  const editor = useRavenMetadataEditor({
    pkg,
    onSaved: (saved) => {
      pkg.value = saved
    },
    onSuccess,
    onError,
    onWarn,
    t,
  })
  return { pkg, editor, onSuccess, onError, onWarn }
}

beforeEach(() => {
  updateMock.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('useRavenMetadataEditor', () => {
  it('exposes canEdit only when the package allows it', () => {
    expect(harness(makePkg()).editor.canEdit.value).toBe(true)
    expect(harness(makePkg({ canEditMetadata: false })).editor.canEdit.value).toBe(false)
    expect(harness(null).editor.canEdit.value).toBe(false)
  })

  it('seeds the description draft from the current package on edit', () => {
    const { editor } = harness(makePkg())
    editor.startEditDesc()
    expect(editor.editingDesc.value).toBe(true)
    expect(editor.descDraft.value).toBe('original')
  })

  it('saves a description and refreshes state, keeping canEditMetadata', async () => {
    const { pkg, editor, onSuccess } = harness(makePkg())
    updateMock.mockResolvedValue({
      data: {
        success: true,
        data: makePkg({ metadata: { description: 'notes', tags: ['orig'] }, canEditMetadata: undefined }),
      },
    })
    editor.startEditDesc()
    editor.descDraft.value = 'notes'
    await editor.saveDesc()

    expect(updateMock).toHaveBeenCalledWith('pkg-1', { description: 'notes' })
    expect(editor.editingDesc.value).toBe(false)
    expect(pkg.value?.metadata?.description).toBe('notes')
    // PATCH response omitted the flag; the composable carries the prior value.
    expect(pkg.value?.canEditMetadata).toBe(true)
    expect(onSuccess).toHaveBeenCalledWith('raven.descSaveSuccess')
  })

  it('keeps the draft and surfaces an error when the save fails', async () => {
    const { pkg, editor, onError } = harness(makePkg())
    updateMock.mockRejectedValue({ response: { data: { detail: 'boom' } } })
    editor.startEditDesc()
    editor.descDraft.value = 'draft-text'
    await editor.saveDesc()

    expect(onError).toHaveBeenCalledWith('boom')
    // Draft retained and still in edit mode for retry/cancel.
    expect(editor.editingDesc.value).toBe(true)
    expect(editor.descDraft.value).toBe('draft-text')
    // Underlying package unchanged.
    expect(pkg.value?.metadata?.description).toBe('original')
    expect(editor.savingDesc.value).toBe(false)
  })

  it('adds, dedups, and removes tags in the draft', () => {
    const { editor, onWarn } = harness(makePkg())
    editor.startEditTags()
    expect(editor.tagsDraft.value).toEqual(['orig'])

    editor.tagInput.value = ' stable '
    editor.addTag()
    expect(editor.tagsDraft.value).toEqual(['orig', 'stable'])
    expect(editor.tagInput.value).toBe('')

    editor.tagInput.value = 'stable'
    editor.addTag()
    expect(editor.tagsDraft.value).toEqual(['orig', 'stable'])
    expect(onWarn).toHaveBeenCalledWith('raven.tagDuplicate')

    editor.removeTag('orig')
    expect(editor.tagsDraft.value).toEqual(['stable'])
  })

  it('saves tags with the normalized draft list', async () => {
    const { pkg, editor, onSuccess } = harness(makePkg())
    updateMock.mockResolvedValue({
      data: { success: true, data: makePkg({ metadata: { description: 'original', tags: ['stable'] } }) },
    })
    editor.startEditTags()
    editor.removeTag('orig')
    editor.tagInput.value = 'stable'
    editor.addTag()
    await editor.saveTags()

    expect(updateMock).toHaveBeenCalledWith('pkg-1', { tags: ['stable'] })
    expect(editor.editingTags.value).toBe(false)
    expect(pkg.value?.metadata?.tags).toEqual(['stable'])
    expect(onSuccess).toHaveBeenCalledWith('raven.tagsSaveSuccess')
  })
})

describe('component metadata editing', () => {
  it('normalizes legacy component strings and copies object rows', () => {
    expect(normalizeComponents('["modem", {"name": "helper", "version": 2}]')).toEqual([
      { name: 'modem' }, { name: 'helper', version: '2' },
    ])
    expect(normalizeComponents('invalid')).toEqual([])
    expect(normalizeComponents([{ name: 123, version: 4 }])).toEqual([{ name: '123', version: '4' }])
  })

  it('isolates drafts, supports add/remove and restores saved rows after cancel', () => {
    const { pkg, editor } = harness(makePkg({ metadata: { components: [{ name: 'modem', version: '1' }] } }))
    editor.startEditComponents()
    editor.componentsDraft.value[0].name = 'changed'
    editor.addComponent()
    editor.removeComponent(0)
    editor.cancelEditComponents()
    expect(pkg.value?.metadata?.components).toEqual([{ name: 'modem', version: '1' }])
    editor.startEditComponents()
    expect(editor.componentsDraft.value).toEqual([{ name: 'modem', version: '1' }])
  })

  it('saves trimmed names and optional versions and retains permission', async () => {
    const { pkg, editor } = harness(makePkg())
    const components = [{ name: 'netconf', version: '' }]
    updateMock.mockResolvedValue({ data: { success: true, data: makePkg({ metadata: { components }, canEditMetadata: undefined }) } })
    editor.startEditComponents()
    editor.addComponent()
    editor.componentsDraft.value[0].name = ' netconf '
    await editor.saveComponents()
    expect(updateMock).toHaveBeenCalledWith('pkg-1', { components })
    expect(pkg.value?.metadata?.components).toEqual(components)
    expect(pkg.value?.canEditMetadata).toBe(true)
    expect(editor.editingComponents.value).toBe(false)
  })

  it('rejects blank names, keeps failed drafts, and allows clearing', async () => {
    const { editor, onWarn, onError } = harness(makePkg())
    editor.startEditComponents()
    editor.addComponent()
    await editor.saveComponents()
    expect(onWarn).toHaveBeenCalledWith('raven.componentNameRequired')
    expect(updateMock).not.toHaveBeenCalled()
    editor.componentsDraft.value[0].name = 'draft'
    updateMock.mockRejectedValue(new Error('failed'))
    await editor.saveComponents()
    expect(onError).toHaveBeenCalledWith('failed')
    expect(editor.editingComponents.value).toBe(true)
    expect(editor.componentsDraft.value[0].name).toBe('draft')
    expect(editor.savingComponents.value).toBe(false)
    editor.removeComponent(0)
    updateMock.mockResolvedValue({ data: { success: true, data: makePkg({ metadata: { components: [] } }) } })
    await editor.saveComponents()
    expect(updateMock).toHaveBeenLastCalledWith('pkg-1', { components: [] })
  })

  it('discards drafts and ignores pending saves when the package changes', async () => {
    const { pkg, editor, onSuccess } = harness(makePkg())
    let resolve!: (value: unknown) => void
    updateMock.mockImplementation(() => new Promise(r => { resolve = r }))
    editor.startEditComponents()
    const pending = editor.saveComponents()
    expect(editor.savingComponents.value).toBe(true)
    await editor.saveComponents()
    expect(updateMock).toHaveBeenCalledTimes(1)
    pkg.value = makePkg({ id: 'pkg-2' })
    expect(editor.editingComponents.value).toBe(false)
    expect(editor.componentsDraft.value).toEqual([])
    resolve({ data: { success: true, data: makePkg() } })
    await pending
    expect(pkg.value.id).toBe('pkg-2')
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('does not open or save components for read-only viewers', async () => {
    const { editor } = harness(makePkg({ canEditMetadata: false }))
    editor.startEditComponents()
    await editor.saveComponents()
    expect(editor.editingComponents.value).toBe(false)
    expect(updateMock).not.toHaveBeenCalled()
  })
})
