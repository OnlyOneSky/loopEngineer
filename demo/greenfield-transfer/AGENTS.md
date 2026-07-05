# Repo conventions (read-only to the coding agent)

- Language: Python 3, stdlib only. Test framework: pytest.
- Source lives in `transferapp/`; acceptance tests live in `tests/acceptance/`.
- Money is `decimal.Decimal`, never float — including intermediate values.
- Every test references the acceptance-criterion id it covers (AC-N) in its
  name or a comment.
- Do not modify existing files when authoring tests; add new files only.
