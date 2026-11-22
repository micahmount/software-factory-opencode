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

The load-bearing rule: **no reviewer runs on a failing build, and no merge
happens without a human.**

## What is in this repository

| Path | Purpose |
|------|---------|
| `DESIGN.md` | Design, upstream porting map, phased plan and licensing decision |
| `factory/checks.sh` | Deterministic static gate |
| `factory/README.md` | Gate checks, dependencies and usage |
| `LICENSE`, `NOTICE` | GPLv3 license text and upstream attribution |

## Status

- [x] Design and upstream-to-OpenCode porting map (`DESIGN.md`)
- [x] Static gate implemented and proven green/red
- [ ] OpenCode agents and command port (Phase 0 spike)
- [ ] One real issue taken end-to-end to an open PR
- [ ] Remit narrowed deliberately (draft/review only, human merges)

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
