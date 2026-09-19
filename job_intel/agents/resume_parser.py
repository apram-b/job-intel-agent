"""Extract a text resume; require bounded, validated profile data."""

from __future__ import annotations
from pathlib import Path
import pdfplumber
from job_intel.core.models import Resume
from job_intel.core.llm import generate


def extract_pdf_text(path):
    file = Path(path)
    if not file.is_file() or file.stat().st_size > 5_000_000:
        raise ValueError("Provide a PDF smaller than 5 MB")
    with pdfplumber.open(file) as pdf:
        if len(pdf.pages) > 10:
            raise ValueError("Resume must contain at most 10 pages")
        text = "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
    if not text:
        raise ValueError("PDF has no selectable text; use a text-based PDF")
    if len(text.encode()) > 30_000:
        raise ValueError("Resume text exceeds 30 KB")
    return text


def parse_resume_node(state):
    try:
        if state.get("resume_data"):
            parsed = Resume.model_validate(state["resume_data"])
        else:
            from datetime import date

            parsed = generate(
                Resume,
                "Extract this candidate's profile. Compute experience from the union of actual non-intern employment date intervals, excluding gaps and overlapping time; use today only for roles explicitly marked Present. Infer seniority from responsibility and title, not years alone; use unknown if unclear. Copy achievements without adding metrics. Do not infer a lead/principal title from tenure.",
                {"today": date.today().isoformat(), "resume": extract_pdf_text(state["resume_path"])},
            )
        return {"resume_data": parsed.model_dump()}
    except Exception as exc:
        return {
            "resume_data": {},
            "errors": [
                f"Resume parsing failed ({type(exc).__name__}); check the PDF or use a reviewed profile JSON"
            ],
        }
