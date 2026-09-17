import type { ChatImageAttachment } from '@/api/chat'

/** Multipart images are file parts, avoiding the text-field cap and Base64 wire overhead. */
export const appendChatImageFiles = (form: FormData, images?: ChatImageAttachment[]) => {
  for (const [index, image] of (images || []).entries()) {
    const payload = image.data.startsWith('data:')
      ? image.data.slice(image.data.indexOf(',') + 1)
      : image.data
    const binary = atob(payload.replace(/\s/g, ''))
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0))
    const extension = image.media_type.split('/')[1] || 'bin'
    form.append('image_files', new Blob([bytes], { type: image.media_type }), `image-${index + 1}.${extension}`)
  }
}
