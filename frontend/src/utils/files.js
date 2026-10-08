export const ATTACHMENT_ACCEPT = '.png,.jpg,.jpeg,.gif,.webp,.pdf,.docx'

const DOCX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export function attachmentIcon(contentType) {
  if (contentType?.startsWith('image/')) return '🖼️'
  if (contentType === 'application/pdf') return '📄'
  if (contentType === DOCX_TYPE) return '📝'
  return '📎'
}

export function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
