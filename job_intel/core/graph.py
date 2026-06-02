"""LangGraph pipeline definition."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from job_intel.agents.career_scraper import scrape_careers_node
from job_intel.agents.company_finder import find_companies_node
from job_intel.agents.job_scorer import score_jobs_node
from job_intel.agents.outreach_drafter import draft_outreach_node
from job_intel.agents.resume_parser import parse_resume_node
from job_intel.core.state import AgentState


def build_graph():
    """Compile and return the pipeline graph.

    Execution order:
        parse_resume → find_companies → scrape_careers → score_jobs → draft_outreach
    """
    g = StateGraph(AgentState)

    g.add_node("parse_resume", parse_resume_node)
    g.add_node("find_companies", find_companies_node)
    g.add_node("scrape_careers", scrape_careers_node)
    g.add_node("score_jobs", score_jobs_node)
    g.add_node("draft_outreach", draft_outreach_node)

    g.add_edge(START, "parse_resume")
    g.add_edge("parse_resume", "find_companies")
    g.add_edge("find_companies", "scrape_careers")
    g.add_edge("scrape_careers", "score_jobs")
    g.add_edge("score_jobs", "draft_outreach")
    g.add_edge("draft_outreach", END)

    return g.compile()
