import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app import schemas
from app.models import Attachment, Comment, User, UserRole, TicketStatus
from app.routers.tickets import _get_ticket_or_404, _assert_can_view, _to_attachment_out

router = APIRouter(tags=["attachments"])

# Screenshots, PDFs, and Word docs only — kept deliberately narrow rather than
# accepting arbitrary uploads.
ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
MAX_SIZE_BYTES = settings.max_upload_size_mb * 1024 * 1024

UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/tickets/{ticket_id}/attachments", response_model=List[schemas.AttachmentOut])
async def upload_attachments(
    ticket_id: int,
    files: List[UploadFile] = File(...),
    comment_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)

    if ticket.status == TicketStatus.closed and current_user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="This ticket is closed and can no longer receive attachments")

    if comment_id is not None:
        comment = db.query(Comment).filter(Comment.id == comment_id, Comment.ticket_id == ticket_id).first()
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found on this ticket")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    saved = []
    for upload in files:
        ext = ALLOWED_CONTENT_TYPES.get(upload.content_type)
        if ext is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type for {upload.filename!r}. Only screenshots (PNG/JPG/GIF/WEBP), PDF, and DOCX are allowed.",
            )

        contents = await upload.read()
        if len(contents) == 0:
            raise HTTPException(status_code=400, detail=f"{upload.filename} is empty")
        if len(contents) > MAX_SIZE_BYTES:
            raise HTTPException(status_code=400, detail=f"{upload.filename} exceeds the {settings.max_upload_size_mb}MB limit")

        stored_name = f"{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / stored_name).write_bytes(contents)

        attachment = Attachment(
            ticket_id=ticket.id,
            comment_id=comment_id,
            uploaded_by_id=current_user.id,
            filename=upload.filename or stored_name,
            stored_name=stored_name,
            content_type=upload.content_type,
            size_bytes=len(contents),
        )
        db.add(attachment)
        saved.append(attachment)

    db.commit()
    for a in saved:
        db.refresh(a)
    return [_to_attachment_out(a) for a in saved]


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    _assert_can_view(attachment.ticket, current_user)

    path = UPLOAD_DIR / attachment.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on server")
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.filename)


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    _assert_can_view(attachment.ticket, current_user)
    if attachment.uploaded_by_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only the uploader or an admin can delete this attachment")

    (UPLOAD_DIR / attachment.stored_name).unlink(missing_ok=True)
    db.delete(attachment)
    db.commit()
