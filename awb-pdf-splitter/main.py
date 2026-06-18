"""API to split a multi-AWB PDF into individual AWB PDFs."""
from __future__ import annotations

import io

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

import storage
from splitter import build_zip, split_pdf

app = FastAPI(title="AWB PDF Splitter", version="1.0.0")

MAX_BYTES = 100 * 1024 * 1024  # 100 MB upload cap


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/split")
async def split(file: UploadFile = File(...)) -> StreamingResponse:
    """Split an uploaded multi-AWB PDF and return a ZIP of per-AWB PDFs."""
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="Upload must be a PDF.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large.")

    try:
        files = split_pdf(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not process PDF: {exc}")

    if not files:
        raise HTTPException(status_code=422, detail="No AWB numbers detected.")

    zip_bytes = build_zip(files)
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="awb-split.zip"'},
    )


@app.post("/split/manifest")
async def split_manifest(file: UploadFile = File(...)) -> JSONResponse:
    """Return only the detected AWB numbers and sizes (no file download)."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    files = split_pdf(data)
    manifest = [{"file": name, "bytes": len(b)} for name, b in files.items()]
    return JSONResponse({"count": len(manifest), "documents": manifest})


@app.post("/split/blob")
async def split_to_blob(
    file: UploadFile = File(...),
    document_name: str = Form(...),
    date: str = Form(...),
    flight: str = Form(...),
) -> JSONResponse:
    """Split a multi-AWB PDF and write each AWB to blob storage.

    Blob layout (configurable via env vars) defaults to:
        <BLOB_CONTAINER>/<document_name>/<date>/<flight>/<awb>.pdf
    """
    if not storage.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Blob upload not configured. Set BLOB_ACCOUNT_URL.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large.")

    try:
        files = split_pdf(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not process PDF: {exc}")

    if not files:
        raise HTTPException(status_code=422, detail="No AWB numbers detected.")

    try:
        written = storage.upload_split_pdfs(
            files,
            document_name=document_name,
            date=date,
            flight=flight,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Blob upload failed: {exc}")

    return JSONResponse({"count": len(written), "blobs": written})
