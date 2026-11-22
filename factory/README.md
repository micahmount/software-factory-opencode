# Static gate

`checks.sh` is the deterministic gate the factory runs before any reviewer and
again before approval. It lives in this repository (the **factory**) and checks a
**project**. It is static only: no network, no deploy, no host access. Anything
requiring runtime verification stays a human step under the project's own rules.

## Run

```bash
bash factory/checks.sh                                    # default project: ../project
FACTORY_PROJECT=/path/to/project bash factory/checks.sh   # explicit project
```

Exit `0` = all checks passed, `1` = at least one check failed. Each check prints
`PASS`, `FAIL`, or `SKIP` with a one-line summary. A missing project is an
immediate failure.

## Dependencies

| Tool | Status | Purpose |
|------|--------|---------|
| `python3` + PyYAML | required | parse YAML/JSON, cross-file assertions |
| `bash` | required | `bash -n` on shell syntax |
| `shellcheck` | optional | lint on changed shell |

If `shellcheck` is absent the lint check is skipped. Set
`FACTORY_REQUIRE_SHELLCHECK=1` to make its absence a failure (recommended for a
factory host or CI).

## What it checks

| Check | What it catches |
|-------|-----------------|
| Shell syntax | `bash -n` on every `*.sh` in the project, plus shell blocks found in YAML (`*.sh` write files, shell shebangs, string `runcmd` entries) |
| YAML | parse failure in every tracked `*.yaml` / `*.yml` — malformed config that fails silently |
| JSON | parse failure in every tracked `*.json` |
| Lint | `shellcheck` on changed shell only — quoting, unset variables, the usual classes of bugs |

The gate is intentionally project-agnostic. Assertions that depend on one
project's file layout do not belong here; they can be added later as a
per-project config.

## Lint scoping

Projects carry legacy shellcheck warnings. Failing on all of them would keep the
gate red forever, so lint is enforced only on **changed shell**, measured with
`git -C "$FACTORY_PROJECT"` against `FACTORY_BASE` (default `trunk`):

- changed `*.sh` files in the project, and
- embedded shell blocks whose content differs from that base version.

Pre-existing findings print as advisory and do not fail the gate. A config-only
edit to a cloud-init file does not turn that file's legacy shell warnings into
failures.

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `FACTORY_PROJECT` | `../project` beside this repo | project to check |
| `FACTORY_BASE` | `trunk` | branch in the project used for lint scoping |
| `FACTORY_REQUIRE_SHELLCHECK=1` | unset | fail when shellcheck is not installed |

## Proving the gate works

Green against a real project:

```bash
FACTORY_PROJECT=/path/to/project bash factory/checks.sh    # expect exit 0
```

Red on a deliberately broken **copy** of a project (do not damage the working
tree):

```bash
rm -rf /tmp/gate-fixture && cp -a /path/to/project /tmp/gate-fixture
FACTORY_PROJECT=/tmp/gate-fixture bash factory/checks.sh
printf '\nif [[\n' >> /tmp/gate-fixture/path/to/script.sh   # shell syntax: expect FAIL
FACTORY_PROJECT=/tmp/gate-fixture bash factory/checks.sh
```

The broken-file path above is illustrative; pick a real `*.sh` in the project.

## Ported factory spine

| Path | Role |
|------|------|
| `bin/job` | State machine, GitHub side effects, cost accounting, session IDs |
| `bin/gate` | Runs the main checkout's `checks.sh` in the job worktree; checks protected paths |
| `bin/route` | Maps intake's risk/surfaces to reviewers and `anthropic/...` models |
| `config.json` | Concurrency, labels, routing, ports and price reference |
| `dashboard.html` | Reads `jobs/<id>/job.json` |

Costs come from OpenCode's session database (`~/.local/share/opencode/opencode.db`,
overridable with `OPENCODE_DB`). The orchestrator records each subagent's
`sessionID` with `job session <job> <name> <id>`; the job header in the first user
prompt is a fallback for older jobs. No Claude transcript parsing is involved.

There is no builder stop hook: the gate always runs after the build, before any
reviewer, and again on handoff.

## Human merge remit

`job handoff` (also callable as `job merge` for compatibility) syncs with the
base branch, re-runs the gate, pushes and readies the PR, then moves the job to
`needs-human`. The factory never merges. A human reviews and merges, or sends
feedback with `job feedback`.

## Install and labels

`factory/install <project>` drops the port into another git checkout. It will
not overwrite an existing installation without `--force`, and it writes
`.opencode/opencode.json` when the project already has a root `opencode.json`.
`factory/labels` creates/updates the three labels named in `config.json`.
