# software-factory-opencode

A software factory built on **OpenCode V2**. It turns a `factory`-labeled issue
into a reviewed, human-approved pull request through a deterministic pipeline.

We use it as tooling to build our own products. The factory is not the product —
the things it builds are.

## Why this exists

The upstream project is an issue-driven factory written for Claude Code. This
repository ports it to OpenCode V2 so the factory uses the same harness,
worktrees and subagents we already use. Judgment calls — intake, spec, build and
approval — stay on frontier models; local models are bounded to read-only and
draft work. A human always makes the final merge call.

## Pipeline

```
issue labeled `factory`
        │
        ▼
intake ── NEEDS-INFO → ask the author, park the job
        │   REJECT   → explain, remove the label
        ▼ ACCEPT; rate risk, surface affected areas
route  → pick reviewers and models from config
        ▼
spec-writer → spec.md
        ▼
builder → isolated worktree, commits, opens a draft PR
        ▼             ▲
gate ─FAIL────────────┤  static checks run before any reviewer
        ▼ PASS        │
reviewers ─CHANGES────┘  code, + ux/ui for UI changes, + security
        ▼ all PASS
approver ── APPROVE → sync, re-run gate, hand to a human to merge
         └─ ESCALATE → PR ready for a human, issue labeled needs-human
```

`APPROVE` runs `factory/bin/job handoff`: it syncs with the base branch, re-runs
the gate, pushes and marks the PR ready. It deliberately does **not** call a
merge command. The load-bearing rule: **no reviewer runs on a failing build,
and no merge happens without a human.**

## What is in this repository

| Path | Purpose |
|------|---------|
| `DESIGN.md` | Design, upstream porting map, phased plan and licensing decision |
| `AGENTS.md` | Project guidance loaded by agents in job worktrees |
| `opencode.json` | V2 config: default model, worktree directory, permissions |
| `.opencode/agents/` | Eight subagents: intake, spec, builder, four review lenses, approver |
| `.opencode/commands/factory.md` | The single orchestrator prompt for `/factory` |
| `factory/bin/job` | Job state machine and GitHub side effects; the only writer of `job.json` |
| `factory/bin/gate` | Runs the main checkout's checks against a job worktree |
| `factory/bin/route` | Maps risk and surfaces to reviewers and model IDs |
| `factory/config.json` | Concurrency, rounds, labels, routing and prices |
| `factory/checks.sh` | Deterministic static gate |
| `factory/dashboard.html` | Local job dashboard |
| `factory/install` | Drops the factory into another project |
| `factory/labels` | Creates the three GitHub labels the factory uses |
| `factory/README.md` | Gate checks, dependencies and usage |
| `LICENSE`, `NOTICE` | GPLv3 license text and upstream attribution |

## Install into a project

From this checkout:

```bash
factory/install /path/to/project
cd /path/to/project && factory/labels
```

The installer copies `factory/`, `.opencode/agents/` and
`.opencode/commands/factory.md`. It preserves an existing `opencode.json` by
writing the factory settings to `.opencode/opencode.json` instead. Runtime state
(`factory/jobs/`, `.worktrees/`) is never copied. Use `--force` to replace an
existing installation. Run `/factory run` in the project to drain its queue.

## Status

- [x] Design and upstream-to-OpenCode porting map (`DESIGN.md`)
- [x] Static gate implemented and proven green/red
- [x] OpenCode agents and command port
- [x] One real issue taken end-to-end to a PR
- [x] Remit narrowed deliberately: draft/review only, human merges

## End-to-end spike

On 22 Nov 2026, issue #4 ("Add a factory smoke test note") went through the
whole pipeline: intake ACCEPT (low risk, no surfaces) → route → spec → builder →
gate PASS → routed code review PASS → approver APPROVE → `job handoff` → human
merge of PR #5. The job added only `SMOKE.md`; the state and evidence remain in
`factory/jobs/001-add-a-factory-smoke/` (`round-1/checks.md`,
`round-1/review-code.md` and `decision.md`), and `job summary` recorded both
`needs-human` after handoff and `merged` after the human merged.

The local runtime had no frontier credentials, so the spike overrode each
subagent with the available `opencode/big-pickle` model. Agent definitions and
`factory/config.json` still route production work to `anthropic/...`; a target
project needs those credentials. The session-ID recording, cost fallback and
resume contract are covered by unit tests.

## Static gate

`factory/checks.sh` is the gate called before review and again before approval.
It is deterministic: shell and config parsing plus lint on changed shell, with
no network or host access. It runs against a project supplied with
`FACTORY_PROJECT`; see [`factory/README.md`](factory/README.md).

```bash
bash factory/checks.sh                              # default: ../project
FACTORY_PROJECT=/path/to/project bash factory/checks.sh
```

Exit `0` means all checks passed, `1` means at least one failed.

## License

GPL-3.0, because the upstream factory is GPLv3. Upstream attribution is in
[`NOTICE`](NOTICE) and the license text in [`LICENSE`](LICENSE); visibility has
nothing to do with credit.

The factory is tooling. Output produced with it is not automatically GPL — only
literal chunks of the factory's GPL-covered code or prompts copied into an
output remain GPL. This is engineering guidance, not legal advice.
