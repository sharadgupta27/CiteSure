from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Response, UploadFile

from app.api.deps import current_user, document_service, get_settings
from app.config import Settings
from app.errors import PayloadTooLarge
from app.schemas import api as s
from app.services.documents import DocumentService

router = APIRouter(tags=["documents"])


@router.get("/collections/{collection_id}/documents", operation_id="listDocuments", response_model=list[s.Document])
async def list_documents(
    collection_id: uuid.UUID, user: s.User = Depends(current_user), svc: DocumentService = Depends(document_service)
) -> list[s.Document]:
    return await svc.list_in_collection(user.id, collection_id)


@router.post(
    "/collections/{collection_id}/documents", operation_id="uploadDocument", status_code=202, response_model=s.Document
)
async def upload_document(
    collection_id: uuid.UUID,
    file: UploadFile = File(...),
    user: s.User = Depends(current_user),
    svc: DocumentService = Depends(document_service),
    settings: Settings = Depends(get_settings),
) -> s.Document:
    data = await file.read(settings.max_upload_bytes + 1)  # never buffer more than the limit plus one byte
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLarge(f"Files can be at most {settings.max_upload_mb} MB")
    return await svc.upload(user.id, collection_id, file.filename or "document", data)


@router.get("/documents/{document_id}", operation_id="getDocument", response_model=s.Document)
async def get_document(
    document_id: uuid.UUID, user: s.User = Depends(current_user), svc: DocumentService = Depends(document_service)
) -> s.Document:
    return await svc.get_document(user.id, document_id)


@router.delete("/documents/{document_id}", operation_id="deleteDocument", status_code=204)
async def delete_document(
    document_id: uuid.UUID, user: s.User = Depends(current_user), svc: DocumentService = Depends(document_service)
) -> Response:
    await svc.delete(user.id, document_id)
    return Response(status_code=204)


@router.post("/documents/{document_id}/reindex", operation_id="reindexDocument", status_code=202, response_model=s.Document)
async def reindex_document(
    document_id: uuid.UUID, user: s.User = Depends(current_user), svc: DocumentService = Depends(document_service)
) -> s.Document:
    return await svc.reindex(user.id, document_id)


@router.get("/documents/{document_id}/file", operation_id="getDocumentFile", response_class=Response)
async def get_document_file(
    document_id: uuid.UUID, user: s.User = Depends(current_user), svc: DocumentService = Depends(document_service)
) -> Response:
    data, mime, filename = await svc.file(user.id, document_id)
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "")
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",  # an uploaded HTML file must not run scripts in our origin
        },
    )


@router.get("/documents/{document_id}/chunks", operation_id="listDocumentChunks", response_model=list[s.Chunk])
async def list_document_chunks(
    document_id: uuid.UUID, user: s.User = Depends(current_user), svc: DocumentService = Depends(document_service)
) -> list[s.Chunk]:
    return await svc.chunks(user.id, document_id)


@router.get("/chunks/{chunk_id}", operation_id="getChunk", response_model=s.Chunk)
async def get_chunk(
    chunk_id: uuid.UUID, user: s.User = Depends(current_user), svc: DocumentService = Depends(document_service)
) -> s.Chunk:
    return await svc.chunk(user.id, chunk_id)
