import { describe, expect, it } from 'vitest'

import {
  configurationManagerRequiresProject,
  formatPackageAttachmentMessage,
  mergeUniquePackageFiles,
} from '@/utils/packageAttachments'

const componentFiles = (count: number): File[] =>
  Array.from({ length: count }, (_, index) =>
    new File([`component-${index + 1}`], `component-${index + 1}.bin`, {
      lastModified: index + 1,
    }),
  )

describe('Configuration Manager component attachments', () => {
  it('lists all thirteen filenames in the optimistic user bubble', () => {
    const files = componentFiles(13)
    const display = formatPackageAttachmentMessage('build package', files, 'Component files')

    expect(display).toContain('Component files (13):')
    for (const file of files) expect(display).toContain(`- ${file.name}`)
  })

  it('restores a failed thirteen-file send without duplicating files already reselected', () => {
    const sent = componentFiles(13)
    const current = [sent[0]]
    const recovered = mergeUniquePackageFiles(current, sent)

    expect(recovered).toHaveLength(13)
    expect(recovered.map((file) => file.name)).toEqual(sent.map((file) => file.name))
  })

  it('requires a project for pure search but permits attachment-bearing packaging unbound', () => {
    expect(configurationManagerRequiresProject(0)).toBe(true)
    expect(configurationManagerRequiresProject(1)).toBe(false)
    expect(configurationManagerRequiresProject(13)).toBe(false)
  })
})
