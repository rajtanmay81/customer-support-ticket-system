import api from '../api/client'
import { attachmentIcon, formatFileSize } from '../utils/files'

export default function AttachmentList({ attachments, onDelete, canDelete }) {
  if (!attachments || attachments.length === 0) return null

  async function handleDownload(a) {
    const res = await api.get(`/attachments/${a.id}/download`, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = a.filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }

  return (
    <div className="attachments">
      {attachments.map((a) => (
        <span key={a.id} className="attachment-chip" onClick={() => handleDownload(a)} title={`Download ${a.filename}`}>
          {attachmentIcon(a.content_type)} {a.filename} <span className="sz">({formatFileSize(a.size_bytes)})</span>
          {canDelete && canDelete(a) && (
            <span
              className="rm"
              title="Delete"
              onClick={(e) => { e.stopPropagation(); onDelete(a) }}
            >
              ✕
            </span>
          )}
        </span>
      ))}
    </div>
  )
}
