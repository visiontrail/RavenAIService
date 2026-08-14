/** Stable browser-side identity used to avoid duplicate picker/drop entries. */
export const packageFileSignature = (file: File): string =>
  `${file.name}:${file.size}:${file.lastModified}`

/** Merge a failed-send snapshot back into the current composer selection. */
export function mergeUniquePackageFiles(current: File[], incoming: File[]): File[] {
  const signatures = new Set(current.map(packageFileSignature))
  const additions = incoming.filter((file) => {
    const signature = packageFileSignature(file)
    if (signatures.has(signature)) return false
    signatures.add(signature)
    return true
  })
  return [...current, ...additions]
}

/** Build the optimistic user-bubble text while preserving every filename. */
export function formatPackageAttachmentMessage(
  message: string,
  files: File[],
  attachmentLabel: string,
): string {
  if (!files.length) return message
  return [
    message,
    '',
    `${attachmentLabel} (${files.length}):`,
    ...files.map((file) => `- ${file.name}`),
  ].join('\n')
}

/** Pure-search turns stay bound; component-bearing packaging may start unbound. */
export const configurationManagerRequiresProject = (componentFileCount: number): boolean =>
  componentFileCount <= 0
