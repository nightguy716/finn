"""Page text from a PDF. pypdf first, PyMuPDF when that reader cannot list the pages."""

import io
import warnings


def page_texts(data: bytes) -> tuple[list[str], str]:
    """Texts in page order, starting at page 1, and the reader that produced them."""
    if not data.startswith(b"%PDF"):
        raise ValueError("not a pdf")
    try:
        texts = _pypdf(data)
    except Exception:
        texts = None
    if texts:
        return texts, "pypdf"
    texts = _mupdf(data)
    if not texts:
        raise RuntimeError("pdf has no pages")
    return texts, "pymupdf"


def _pypdf(data: bytes) -> list[str]:
    from pypdf import PdfReader

    warnings.filterwarnings("ignore", message="fontTools is required")
    reader = PdfReader(io.BytesIO(data), strict=False)
    total = len(reader.pages)
    if total <= 0:
        raise RuntimeError("pypdf listed no pages")
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            texts.append("")
    return texts


def _mupdf(data: bytes) -> list[str]:
    import pymupdf

    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        if document.page_count <= 0:
            return []
        return [page.get_text() or "" for page in document]
    finally:
        document.close()
