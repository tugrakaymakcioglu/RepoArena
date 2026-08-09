# Architecture

RepoArena is a local orchestration process around three trust zones:

1. The **discovery zone** may inspect full local history and GitHub metadata. It creates internal
   tasks containing historical commit IDs and verifier-only patches.
2. The **solver zone** receives a one-commit synthetic repository and a sanitized `SolverTaskV1`.
   It emits only a Git patch. It never receives verifier artifacts or the original remote.
3. The **verifier zone** reconstructs the base independently, validates and applies the solver patch,
   restores hidden tests, performs setup, disables networking, and runs the recorded test command.

SQLite is the source of truth for task and run state. JSON schemas are represented by strict Pydantic
models, carry an explicit version, and are stored separately for public task and verifier data.

Git and Docker are invoked with argument arrays. RepoArena never checks out, resets, cleans, or edits
the user's active worktree during discovery or benchmarking. A private bare mirror under
`.repoarena/cache` is used only when the active object database lacks historical commits.

Benchmark sessions hash the complete canonical task definitions before the first run. Reports only
compare completed sessions with the same task-set hash. Agents execute sequentially to avoid timing
contention and receive a fresh solver workspace for every task. Interrupted RUNNING rows are closed
explicitly before a later session starts.
