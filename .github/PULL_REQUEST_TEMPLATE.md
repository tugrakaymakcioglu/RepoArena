## Summary

Describe the problem and the smallest coherent change that solves it.

## Validation

- [ ] Tests added or updated for behavior changes
- [ ] `uv run pytest`
- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run mypy src`
- [ ] `uv build`

## Trust boundary

- [ ] I considered historical-task validity and reproducibility.
- [ ] I considered solver-to-verifier leakage and protected artifacts.
- [ ] I did not add credentials, private source, benchmark databases, or real provider recordings.
- [ ] Provider calls, if any, are opt-in and never required by normal CI.

## Documentation

List user-facing documentation changes or explain why none are needed.
