from job_intel.core.presentation import public_result


def test_download_omits_diagnostics_but_keeps_job_links():
    result = {
        "source_checks": ["private"],
        "errors": ["private"],
        "usage": {},
        "companies": [],
        "ranked_listings": [{"url": "https://www.linkedin.com/jobs/view/123"}],
    }
    exported = public_result(result)
    assert set(exported) == {"ranked_listings"}
    assert exported["ranked_listings"][0]["url"].endswith("123")
    assert "errors" in result
