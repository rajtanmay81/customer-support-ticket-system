import { ATTACHMENT_ACCEPT, formatFileSize } from '../utils/files'

export default function FilePicker({ files, onChange, disabled }) {
  function handleSelect(e) {
    const picked = Array.from(e.target.files || [])
    onChange([...files, ...picked])
    e.target.value = ''
  }

  function removeAt(idx) {
    onChange(files.filter((_, i) => i !== idx))
  }

  return (
    <div>
      <label className={`ghost btn-sm${disabled ? ' disabled' : ''}`} style={{ cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1 }}>
        <input type="file" multiple accept={ATTACHMENT_ACCEPT} onChange={handleSelect} disabled={disabled} style={{ display: 'none' }} />
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" /></svg>
        Attach files
      </label>
      <span className="hint" style={{ marginLeft: 8 }}>Screenshots, PDF, DOCX — up to 10MB each</span>

      {files.length > 0 && (
        <div className="attachments" style={{ marginTop: 10 }}>
          {files.map((f, i) => (
            <span key={`${f.name}-${i}`} className="attachment-chip">
              📎 {f.name} <span className="sz">({formatFileSize(f.size)})</span>
              <span className="rm" onClick={() => removeAt(i)} title="Remove">✕</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
