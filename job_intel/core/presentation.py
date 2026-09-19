"""Public exports deliberately omit operational diagnostics."""


def public_result(result):
    return {
        key: value
        for key, value in result.items()
        if key not in {"source_checks", "errors", "usage", "companies"}
    }
