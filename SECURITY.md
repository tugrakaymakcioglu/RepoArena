# Security policy

## Supported versions

RepoArena is currently alpha software. Security fixes are applied to the latest revision on `main`
and the most recent published alpha release, when releases exist. Older snapshots are not supported.

## Report a vulnerability

Use [GitHub Security Advisories](https://github.com/tugrakaymakcioglu/RepoArena/security/advisories/new)
to report vulnerabilities privately. Do not open a public issue for an unpatched vulnerability.

Include only the minimum information needed to reproduce the problem:

- affected RepoArena revision or version;
- operating system, Python version, Git version, and Docker version;
- affected trust boundary: discovery, solver, verifier, storage, report, or credentials;
- a synthetic proof of concept when possible;
- the expected security property and observed behavior.

Do not include real API keys, private repository content, provider session recordings, or a user's
`.repoarena` database. If sensitive evidence is unavoidable, wait for the maintainer to provide a
safe transfer method.

## Response process

The maintainer will acknowledge a complete report when practical, validate impact, coordinate a
fix, and credit the reporter if requested. Timelines depend on severity and maintainer availability;
the project does not currently promise a formal service-level agreement.

## Security scope

RepoArena treats benchmarked repositories as potentially hostile. High-impact areas include archive
extraction, Git history isolation, task sanitization, patch parsing, Docker mounts and networks,
credential forwarding, log redaction, SQLite persistence, and HTML escaping.

Provider handling of code sent by a selected coding agent is governed by that provider and is not a
RepoArena vulnerability unless RepoArena violates its documented forwarding or isolation behavior.
