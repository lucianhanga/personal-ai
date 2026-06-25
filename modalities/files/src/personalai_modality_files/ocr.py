"""Optional OCR fallback for scanned / image-only PDFs (#450).

A scanned PDF has no embedded text layer, so ``pypdf`` extracts nothing. Here we render each
page to a raster image (``pypdfium2`` -- PDFium, BSD) and run on-device OCR (RapidOCR =
PaddleOCR models via ONNX Runtime, Apache-2.0). Fully offline: the recognition models ship in
the wheel, so nothing leaves the host -- the same privacy guarantee as the rest of the stack.

OCR is treated as an OPTIONAL capability. If the dependencies are missing, ``ocr_available()``
is ``False`` and ``ocr_pdf`` raises :class:`OcrUnavailableError`; callers then fall back to the
empty-text ("no text found") behavior, so a slim install degrades gracefully.
"""

from __future__ import annotations

import threading

# 200 DPI is the measured sweet spot (#450 benchmark): same text as 300 DPI, ~2x faster.
_DEFAULT_DPI = 200

# RapidOCR loads ONNX models once (~0.9s); cache a single engine across calls. The engine is
# created under a lock so concurrent first-calls don't each build one.
_engine: object | None = None
_engine_lock = threading.Lock()


class OcrUnavailableError(RuntimeError):
    """Raised when OCR is requested but its optional dependencies are not installed."""


def ocr_available() -> bool:
    """Return ``True`` if the optional OCR dependencies (rapidocr + pypdfium2) are importable."""
    try:
        import pypdfium2  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _get_engine() -> object:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                except Exception as exc:  # pragma: no cover - guarded by ocr_available()
                    raise OcrUnavailableError("OCR dependencies are not installed") from exc
                _engine = RapidOCR()
    return _engine


def ocr_pdf(content: bytes, *, dpi: int = _DEFAULT_DPI) -> str:
    """Render every page of ``content`` and OCR it; return the concatenated page text.

    This is CPU-bound and slow relative to a text-layer parse (~0.6s/page), so callers should
    run it off the event loop (e.g. ``asyncio.to_thread``). Raises :class:`OcrUnavailableError`
    when the optional OCR dependencies are unavailable.
    """
    try:
        import pypdfium2 as pdfium
    except Exception as exc:  # pragma: no cover - guarded by ocr_available()
        raise OcrUnavailableError("OCR dependencies are not installed") from exc

    engine = _get_engine()
    scale = dpi / 72.0
    pages: list[str] = []
    pdf = pdfium.PdfDocument(content)
    try:
        for page in pdf:
            bitmap = page.render(scale=scale)
            image = bitmap.to_numpy()
            result, _ = engine(image)  # type: ignore[operator]
            if result:
                pages.append("\n".join(line[1] for line in result))
    finally:
        pdf.close()
    return "\n\n".join(pages)
