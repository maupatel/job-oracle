"""
Cover-letter export: turn edited letter text into downloadable PDF / DOCX bytes.

PDF  -> fpdf2 (pure Python)
DOCX -> python-docx

Both return raw bytes suitable for Streamlit's st.download_button.
"""

from __future__ import annotations
import io


def to_pdf(text: str, name: str = "Cover Letter") -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="Letter")          # default unit = mm
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_margins(20, 20, 20)
    pdf.set_font("Helvetica", size=11)
    # fpdf2 core fonts are latin-1; map the bullet to a latin-1 middle dot and
    # replace any other stray unicode so output never crashes.
    safe = text.replace("•", "·").encode("latin-1", "replace").decode("latin-1")
    for line in safe.split("\n"):
        if line.strip() == "":
            pdf.ln(5)
        else:
            pdf.multi_cell(pdf.epw, 6, line)   # explicit width; w=0 errors in 2.8.7
    return bytes(pdf.output())           # fpdf2 returns a bytearray


def to_docx(text: str, name: str = "Cover Letter") -> bytes:
    import docx
    from docx.shared import Pt

    d = docx.Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


if __name__ == "__main__":
    sample = "June 07, 2026\n\nDear Hiring Team,\n\nThis is a test letter.\n\nSincerely,\nName"
    print("PDF bytes:", len(to_pdf(sample)))
    print("DOCX bytes:", len(to_docx(sample)))
