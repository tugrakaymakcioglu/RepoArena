# GitHub repository metadata

Use this copy when publishing RepoArena. It is deliberately concise, searchable, and limited to
implemented behavior.

## Repository name

`RepoArena`

## About description

> SWE-bench for your own repository. Compare AI coding agents on real historical issues with isolated, reproducible verification.

## Topics

```text
ai
ai-agents
ai-coding
benchmark
cli
coding-agents
developer-tools
docker
github
gemini
llm-evaluation
llm-router
local-first
openrouter
open-source
privacy-first
python
software-engineering
swe-bench
testing
```

GitHub topics are lowercase and public. Keep the list focused; unrelated high-volume tags reduce
trust rather than improving discovery.

## Social preview copy

Use a 1280 × 640 PNG with a solid dark background and only this copy:

```text
RepoArena
SWE-bench for your repository.
Benchmark coding agents on real project history.
```

Do not add provider logos in a way that implies endorsement. Keep essential text inside generous
safe margins so link previews do not crop it.

## Suggested first release

- Tag: `v0.1.1`
- Title: `RepoArena v0.1.1 — Gemini and router benchmark support`
- Summary: `Alpha update adding Gemini CLI, OpenRouter and OpenAI-compatible router adapters while preserving leakage-resistant solver snapshots, independent Docker verification, local SQLite persistence and self-contained reports.`

Create the release only after CI passes from a committed revision. Do not publish provider keys,
`.repoarena/` runtime data, private fixture content, or local reports.

## Public launch checklist

- Set the About description and topics above.
- Upload a social preview image in repository settings.
- Enable GitHub Discussions before publishing the support links.
- Enable private vulnerability reporting.
- Protect `main` with passing CI and pull-request review requirements.
- Keep Actions permissions read-only unless a workflow explicitly needs more.
- Confirm the community profile recognizes README, LICENSE, CONTRIBUTING, CODE_OF_CONDUCT,
  SECURITY, issue templates, and pull request template.
- Run installation commands from a clean clone on Python 3.12 and 3.13.
- Verify that `.repoarena/repoarena.db`, caches, runs, reports, and credentials are absent from Git.

GitHub references: [repository README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes),
[repository topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics),
and [community profiles](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories).
