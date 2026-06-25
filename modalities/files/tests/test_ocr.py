"""OCR fallback for scanned / image-only PDFs (#450).

The end-to-end test generates a real image-only PDF (text rasterized into an image, so there is
NO text layer) and asserts RapidOCR recovers the words. It is skipped if the optional OCR deps
(or the fixture builders Pillow/fpdf2) are unavailable, so a slim install still runs the suite.
"""

from __future__ import annotations

import io

import pytest

from personalai_modality_files import ocr_available, ocr_pdf
from personalai_modality_files.ocr import OcrUnavailableError


def _image_only_pdf(text: str) -> bytes:
    """Build a single-page PDF whose only content is a raster image of ``text`` (no text layer)."""
    PIL_Image = pytest.importorskip("PIL.Image")
    PIL_Draw = pytest.importorskip("PIL.ImageDraw")
    fpdf = pytest.importorskip("fpdf")

    # Render text large so OCR has clean glyphs: draw on a small canvas, then upscale.
    img = PIL_Image.new("RGB", (300, 100), "white")
    PIL_Draw.Draw(img).text((10, 40), text, fill="black")
    img = img.resize((1200, 400))

    pdf = fpdf.FPDF(unit="pt", format=(600, 200))
    pdf.add_page()
    pdf.image(img, x=0, y=0, w=600, h=200)  # fpdf2 accepts a PIL image directly
    return bytes(pdf.output())


def test_ocr_available_reports_deps() -> None:
    # Must return a clean bool whether or not the optional deps happen to be installed.
    assert isinstance(ocr_available(), bool)


def test_ocr_pdf_recovers_text_from_image_only_pdf() -> None:
    if not ocr_available():
        pytest.skip("OCR dependencies not installed")
    data = _image_only_pdf("HELLO WORLD")

    # Sanity: the fixture truly has no text layer, so a normal parse would extract nothing.
    from pypdf import PdfReader

    layer = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    assert layer.strip() == ""

    recovered = ocr_pdf(data).upper()
    assert "HELLO" in recovered
    assert "WORLD" in recovered


def test_ocr_pdf_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Slim install: a failed pypdfium2 import -> OcrUnavailableError, not a raw ImportError.
    import builtins

    real_import = builtins.__import__

    def _no_pdfium(name: str, *args: object, **kwargs: object) -> object:
        if name == "pypdfium2":
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_pdfium)
    with pytest.raises(OcrUnavailableError):
        ocr_pdf(b"%PDF-1.4")
