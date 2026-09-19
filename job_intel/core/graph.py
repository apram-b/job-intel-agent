"""Conditional workflow; dependent stages never run on missing inputs."""

from langgraph.graph import END, START, StateGraph
from job_intel.core.state import AgentState
from job_intel.agents.resume_parser import parse_resume_node
from job_intel.agents.company_finder import find_companies_node
from job_intel.agents.career_scraper import scrape_careers_node
from job_intel.agents.job_scorer import score_jobs_node
from job_intel.agents.outreach_drafter import draft_outreach_node


def build_graph():
    graph = StateGraph(AgentState)
    for name, node in [
        ("parse_resume", parse_resume_node),
        ("find_companies", find_companies_node),
        ("scrape_careers", scrape_careers_node),
        ("score_jobs", score_jobs_node),
        ("draft_outreach", draft_outreach_node),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "parse_resume")
    graph.add_conditional_edges("parse_resume", lambda s: "find_companies" if s.get("resume_data") else END)
    graph.add_conditional_edges("find_companies", lambda s: "scrape_careers" if s.get("companies") else END)
    graph.add_conditional_edges("scrape_careers", lambda s: "score_jobs" if s.get("job_listings") else END)
    graph.add_conditional_edges("score_jobs", lambda s: "draft_outreach" if s.get("ranked_listings") else END)
    graph.add_edge("draft_outreach", END)
    return graph.compile()
