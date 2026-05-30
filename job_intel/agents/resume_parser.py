"""Agent: parse a PDF resume into structured ResumeData using pdfplumber + Claude Haiku."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from job_intel.core.state import AgentState, ResumeData
from job_intel.db.store import save_resume

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_pdf_text(path: str) -> str:
    """Return all text from a PDF, pages joined with newlines."""
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages).strip()


def _parse_with_llm(resume_text: str) -> ResumeData:
    from datetime import date
    today = date.today().isoformat()

    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

    prompt = f"""You are a resume parser. Today's date is {today}.

Return ONLY a JSON object with these exact keys:
{{
  "name": "Full Name",
  "current_role": "Most recent job title",
  "years_experience": <float, see calculation rules below>,
  "skills": ["skill1", "skill2", ...],
  "stack": ["technology1", "technology2", ...],
  "inferred_field": "A concise field label, e.g. 'MLOps Engineering', 'Frontend Development'"
}}

years_experience calculation rules (follow exactly):
1. List every role on the resume with its start date.
2. EXCLUDE any role whose title contains "Intern", "Internship", "Trainee", or "Student".
3. From the remaining roles, find the EARLIEST start date.
4. Calculate the number of years from that earliest start date to today ({today}).
5. Round to one decimal place (e.g. 4.5).

Other guidelines:
- skills: programming languages, frameworks, ML/data tools, methodologies
- stack: infrastructure, cloud platforms, databases, DevOps tools
- inferred_field: derive from overall career trajectory, not just the latest title

RESUME:
{resume_text}"""

    msg = llm.invoke([HumanMessage(content=prompt)])
    raw = msg.content if isinstance(msg.content, str) else ""

    match = _JSON_RE.search(raw)
    if not match:
        raise ValueError(f"LLM did not return a JSON object. Response:\n{raw[:500]}")

    data = json.loads(match.group())

    years = round(float(data.get("years_experience", 0)), 1)

    if years < 2:
        seniority = "junior"
    elif years < 4:
        seniority = "mid"
    elif years < 7:
        seniority = "senior"
    else:
        seniority = "lead/principal"

    return ResumeData(
        name=str(data.get("name", "")).strip(),
        current_role=str(data.get("current_role", "")).strip(),
        years_experience=years,
        skills=[str(s).strip() for s in data.get("skills", [])],
        stack=[str(s).strip() for s in data.get("stack", [])],
        inferred_field=str(data.get("inferred_field", "")).strip(),
        seniority_level=seniority,
    )


def parse_resume_node(state: AgentState) -> dict:
    """LangGraph node: extract PDF text, parse with Claude, persist to SQLite."""
    path = state["resume_path"]

    if not Path(path).exists():
        return {"errors": [f"resume_parser: file not found: {path}"]}

    try:
        resume_text = _extract_pdf_text(path)
    except Exception as exc:
        return {"errors": [f"resume_parser: PDF extraction failed: {exc}"]}

    if not resume_text:
        return {"errors": ["resume_parser: PDF produced no extractable text"]}

    try:
        resume_data = _parse_with_llm(resume_text)
    except Exception as exc:
        return {"errors": [f"resume_parser: LLM parsing failed: {exc}"]}

    try:
        save_resume(resume_data)
    except Exception as exc:
        # Non-fatal — log but don't abort
        return {"resume_data": resume_data, "errors": [f"resume_parser: DB save failed: {exc}"]}

    return {"resume_data": resume_data}
