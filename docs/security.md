# Threat model

## Protected assets

- future Git history and the human solution
- hidden verification tests and expected outcomes
- provider and GitHub credentials
- the user's active checkout and unrelated host files
- private source code and local benchmark results

## Enforced boundaries

Solver snapshots are created with `git archive` and reinitialized as a one-commit repository. No
remote, branch, tag, reflog, unreachable future object, RepoArena state, or task metadata file is
present. Patch paths and sizes are validated before a separate verifier applies them.

Containers run without the Docker socket, with a read-only root, bounded CPU/memory/PIDs/time, all
Linux capabilities dropped, and `no-new-privileges`. Only the workspace and an explicitly selected
credential file may be mounted into a solver. The verifier receives no credentials. Final tests use
Docker's `none` network.

Agent home directories are separate ephemeral tmpfs mounts. Environment-backed API-key values are
passed to the Docker client through its process environment rather than `--env KEY=value` command
arguments. Values are redacted from captured output and checked against generated patches before an
artifact is written.

Provider-only networking places the solver on an internal Docker network. A Squid sidecar is the only
member with an external network and permits CONNECT only to configured provider suffixes. GitHub and
general internet access are not allowed from the solver.

For local routers, only the proxy sidecar receives a `host.docker.internal` host-gateway mapping and
the configured allowlist must explicitly name that host. This does not secure the router itself.
Keep local router software current, require its API key, bind it narrowly, and use host firewall
rules so unrelated network clients cannot reach it.

## Residual risks

The selected provider receives the prompt and code the agent sends. Repository instructions may try
to influence the coding agent, and a provider credential must be usable by that provider's CLI.
Provider-only egress limits arbitrary exfiltration but cannot prevent content from being sent to the
chosen provider. Run RepoArena only with provider accounts and repositories whose policies permit
that processing.

Dependency installation may use network access before final verification. It runs without provider
credentials but can execute untrusted package hooks inside the bounded verifier container. Set
`setup_network = "none"` and use a prebuilt custom verifier image for fully offline verification.
