# Design: a software factory on OpenCode

**Status:** accepted — port implemented; end-to-end spike complete; auto-merge run verified
**Date:** 17 Nov 2026
**Updated:** 22 Nov 2026 (port landed, install support added, spike proven, upstream approval semantics restored, auto-merge run verified)
**Upstream:** [`zazencodes/zazencodes-season-3/src/software-factory-claude-code-v2`](https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code-v2) (GPLv3)

## 1. Summary

The upstream "software factory" is an **issue-driven agent pipeline**: label a
GitHub issue `factory`, run `/factory run`, and one orchestrator session drives
`intake → spec → build → gate → review → approve`, ending in one PR per issue.

It is written for Claude Code. This repo's harness is **OpenCode**. Two
questions, two answers:

| Question | Verdict |
|---|---|
| Can it be ported to OpenCode? | **Yes, high confidence.** ~90% of the source is harness-agnostic. The Claude-specific surface is three things: agent/skill packaging, one builder hook, and cost accounting. |
| Should it be adopted *on a project repo*? | **Partly.** The port is cheap. The fit is the hard part: projects rarely have one universal test suite, and runtime verification stays a human responsibility — a static gate cannot satisfy that. |

Recommendation: **port it, then scope its remit deliberately** (see §9, Phase 3).
Adopt the upstream approval contract: the approver is a judgment gate that
`APPROVE auto-merges` in-scope changes and uses `ESCALATE parks the job` only for
the specific risks listed in its agent definition. Keep those risk lists tailored
to the target project.

## 2. Background: how the factory works

```
issues labeled `factory`
        │
        ▼
intake (fable) ── NEEDS-INFO → asks the author, parks the job
        │         REJECT     → says why, removes the label
        ▼ ACCEPT, maybe rescoped; rates risk + surfaces
route (script)    picks reviewers and models from config.json
        ▼
spec-writer (opus) → spec.md
        ▼
builder (opus) → commits, pushes, opens a draft PR "Closes #n"
        ▼            ▲
gate (script) ─FAIL──┤  factory/checks.sh; no reviewer runs on a failing build
        ▼ PASS       │
reviewers ─CHANGES───┘  code, + ux & ui on UI changes, + security
        ▼ all PASS
approver (opus) ── APPROVE  → sync with main, gate again, gh pr merge
                └─ ESCALATE → PR ready for a human, issue labeled factory:needs-human
```

The load-bearing insight: **the deterministic stages are plain Python + `git` +
`gh`**, and only the *agents* and the *orchestrator prompt* are LLM/harness
specific.

| Piece | File | Harness-specific? |
|---|---|---|
| Orchestrator | `.claude/skills/factory/SKILL.md` | yes (prompt + tool names) |
| 8 agents | `.claude/agents/*.md` | partly (frontmatter) |
| State spine | `factory/bin/job` | no, except cost accounting |
| Gate | `factory/bin/gate` | no, except the `--hook` mode |
| Routing | `factory/bin/route` | no |
| Checks | `factory/checks.sh` | generic by design |
| Dashboard | `factory/dashboard.html` | no (reads `job.json`) |
| Config | `factory/config.json` | model IDs only |

## 3. Why a port is needed at all

The factory requires **Claude Code ≥ 2.1.257** (intake runs on the Fable model).
The workstation has **2.0.47**, so the upstream cannot be installed as-is.

OpenCode is already this repo's harness:

- `opencode.json` at the repo root loads skills from `./skills`
  (`skills/<skill>/SKILL.md`).
- OpenCode V2 can run headless with an API, so the factory is not tied to a UI.
- The workstation runs OpenCode V2 with an `anthropic` credential.

OpenCode V2 also has **native worktrees** (a `worktree` table, plus
`worktree_create`/`list`/`remove`) — which is exactly the factory's isolation
model — and a `subagent` tool that matches the orchestrator contract: background
children, a notification each time one goes idle, resume by `sessionID`.

## 4. Port surface

### 4.1 The complete Claude-specific inventory

| Claude Code dependency | Where | OpenCode V2 equivalent | Effort |
|---|---|---|---|
| `.claude/skills/factory/SKILL.md` | skill | `.opencode/skills/factory/SKILL.md` — **`.claude/skills` is a documented compatibility source, so this already loads** | none |
| `/factory run` slash command | skill invocation | a real `.opencode/commands/factory.md` (commands take `$ARGUMENTS`; skills are not slash commands) | small |
| `.claude/agents/*.md` (`name`, `description`, `tools`, `model`, `hooks`) | 8 agents | `.opencode/agents/*.md` (`description`, `mode: subagent`, `model`, `permissions`). **No `.claude/agents` compatibility source is documented** | mechanical |
| `tools: Read, Grep, Glob, Bash, Write` | agents | `permissions: [{action: shell, resource: "*", effect: allow}]` etc. (`shell`, `edit`, `read`, `subagent`) | mechanical |
| `model: opus \| haiku \| sonnet \| fable` | agents + `config.json` routing | `anthropic/claude-opus-5-5`, `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-fable-5-2` | trivial |
| Builder `Stop` hook → `gate --hook` (reads `agent_transcript_path`) | `builder.md` + `bin/gate` | OpenCode plugin hook, or delete (the gate still runs after the build) | small |
| `cost_usd()` scrapes `~/.claude/projects/**/subagents/agent-*.jsonl` | `bin/job` | OpenCode's DB already stores it: `session(cost, tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write, model)` | small |
| `$CLAUDE_PROJECT_DIR`, `CLAUDE_CONFIG_DIR`, "20 concurrent subagents" | hook, `bin/job`, SKILL.md prose | none needed; re-word | trivial |
| "Agent tool", `subagent_type`, `SendMessage` to resume | SKILL.md prose | `subagent` tool with `agent` + `model`, resumed by `sessionID` | small |

### 4.2 What runs unchanged

`job queue/create/advance/merge/feedback/reject/agents/sync/summary`, `gate`
(minus `--hook`), `route`, `config.json`, `dashboard.html`, `checks.sh`, the
worktree-per-job model, the prompt-injection discipline (issue text quoted as
data, never in a prompt), and the label-as-trust-boundary guardrail.

### 4.3 Model routing maps almost 1:1

The upstream `config.json` already prices `claude-fable-5-1 / opus-5-5 /
sonnet-5-5 / haiku-5-5`; the local Anthropic provider exposes `claude-fable-5-2
/ opus-5-5 / sonnet-5-5 / haiku-5-5`. The routing table needs only the
`provider/model` prefix.

| Risk / surface | Upstream reviewer | Ported to |
|---|---|---|
| low | haiku | `anthropic/claude-haiku-5-5` |
| medium / high | sonnet | `anthropic/claude-sonnet-5-5` |
| `+ui` | ux sonnet, ui haiku | `anthropic/claude-sonnet-5-5`, `anthropic/claude-haiku-5-5` |
| `+security` | security opus | `anthropic/claude-opus-5-5` |
| builder / spec / approver | opus | `anthropic/claude-opus-5-5` |
| intake | fable | `anthropic/claude-fable-5-2` |

Local models are deliberately **not** in this table: they are reserved for
read-only/draft subagents, never for the factory's gatekeeping roles.

## 5. Target layout in this repo

```
opencode.json                     skills array already points at ./skills
.opencode/
  commands/factory.md             the orchestrator prompt (was SKILL.md)
  agents/intake.md                mode: subagent
  agents/spec-writer.md
  agents/builder.md
  agents/reviewer-code.md
  agents/reviewer-security.md
  agents/reviewer-ux.md
  agents/reviewer-ui.md
  agents/approver.md
factory/
  config.json                     base_branch: trunk, model IDs, prices
  checks.sh                       this repo's gate (see §6)
  bin/job  bin/gate  bin/route    ported; job's cost query rewritten
  dashboard.html
.gitignore                        + /factory/jobs/  + /.worktrees/
```

`factory/` stays at the repo root so the upstream scripts (`parents[1]`,
`parents[2]`) resolve without edits.

## 6. The gate problem — the crux

The factory's whole safety story is `factory/checks.sh`: **no reviewer runs on a
failing build, and the approver re-runs it before merging.** Projects rarely
share one test suite, so the gate is authored here and stays static-only.

### 6.1 What `checks.sh` does

| Check | Command | Catches |
|---|---|---|
| Shell syntax | `bash -n` every `*.sh` plus shell blocks found in YAML | a typo that would fail at runtime |
| Lint | `shellcheck` on changed shell only | quoting, unset variables, the usual classes of bugs |
| YAML | parse every `*.yaml` / `*.yml` | malformed config that fails silently |
| JSON | parse every `*.json` | malformed config |

The gate is deliberately project-agnostic. Assertions that depend on one
project's file layout belong in a per-project config, not hardcoded here.

### 6.2 What the gate cannot do

It cannot deploy, contact hosts, or verify runtime state. Anything requiring
runtime verification stays a human step under the project's own rules.

### 6.3 Consequence for the approver

The approver follows upstream: `APPROVE auto-merges` an in-scope change after the
merge-time re-gate, while `ESCALATE parks the job` only for its explicit
conditions — failed criteria or changes touching money/access/identity,
deploy/CI/hosting, schemas, production data, dependencies, or product/business
decisions. Each project tailors those lists; the approver should not escalate
merely to be safe.

## 7. Where it runs

| Option | Pros | Cons |
|---|---|---|
| Workstation | interactive, credentials already present | must be awake |
| Always-on server | available continuously | needs the repo, credentials and a factory checkout on that host |

Start on the workstation. Treat an always-on server as a later, optional host.

## 8. Model track — results

Local models were qualified for read-only and draft subagent work only. They are
not in the routing table in §4.3 and never take a gatekeeping role: builder,
spec and approval stay on frontier models. Concrete model aliases and benchmark
details are deployment concerns, not part of the factory design.

## 9. Phased plan

The model track, gate, OpenCode port, drop-in installer and end-to-end spike are
complete. Implementation order differed from the numbering: **the gate (item 2)
was built before the spike (item 1)**, because the spike's `gate` stage calls `checks.sh`
and upstream's version is not useful for a generic project. A gate that is green
on the base branch and red on a broken fixture is what makes the spike
meaningful.

1. **Phase 0 — spike (no repo risk).** Done: ported the agents and command,
   dropped the hook, rewrote `job`'s cost query and set `concurrency: 1`. The
   spike took issue #4 → PR #5 through `intake`, `spec`, `build`, `gate` and
   `review`, recording every subagent session ID. It used an interim human-merge
   path; the upstream `APPROVE → job merge` contract was restored after
   re-reading the source. A second real run then took issue #10 → PR #11 on the
   restored auto-merge path: `APPROVE` called `job merge`, which re-synced,
   re-ran the gate and merged the PR with no human merge call. Both runs needed
   no second build round, so the resume path is covered by the `subagent`
   contract and unit tests rather than a live retry; cost has DB and API
   fallbacks.
2. **Phase 1 — make the gate real.** Done: `factory/checks.sh` passes on the
   base branch and fails on a deliberately broken shell fixture. The gate is
   static-only and runs against `FACTORY_PROJECT`.
3. **Phase 2 — land the port.** Done: `.opencode/` + `factory/` + project docs
   + `.gitignore` + labels are on `main`. One real issue went through to a
   merged PR, and every stage decision is recorded on disk.
4. **Phase 3 — scope the remit.** Decided: follow upstream. The approver is a
   judgment gate: `APPROVE` calls `job merge`, which re-syncs, re-runs the gate
   and calls `gh pr merge`. `ESCALATE` parks the job for a human only for the
   approver's enumerated high-risk or failed-criteria conditions.

## 10. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| **GPLv3** | the port is a derivative work of a GPLv3 program | decided: direct port published as GPLv3 with upstream LICENSE + NOTICE; sell the *outputs*, not the factory. See below. |
| Gate is static-only | a passing branch can still break runtime behaviour | approver escalates the enumerated runtime-shaped risks; low-risk in-scope changes auto-merge after the re-gate |
| No test suite | the gate is new code with no tests | keep it small and deterministic; test it against known-bad files |
| Builder hook rewrite | upstream nudge is lost if dropped | the gate already enforces after the build; a plugin hook is optional polish |
| Cost accounting | upstream's transcript format is Claude-specific | OpenCode stores cost/tokens per session; sum the child sessions tied to a job |
| Concurrency | upstream assumes 20 concurrent subagents; 3 jobs × 4 reviewers = 12 | verify OpenCode's limit before raising `concurrency` |
| Secrets in issues | issue text reaches agents as data | keep the upstream rule: quoted data only, never a prompt; intake has no shell |
| Local models too weak | builder/approver on a small local model would produce noise | route gatekeeping roles at frontier models, not local ones |

### Licensing and commercial use

The upstream repo is **GPL-3.0**, confirmed both at repo level and by the
`LICENSE` inside `software-factory-claude-code-v2`. A direct port is therefore a
derivative work.

**Decision (22 Nov 2026): direct port, published publicly under GPLv3.** This
repository is the OpenCode V2 conversion of the upstream factory and is public.
Publishing is "conveying" under GPLv3, so the port and our original files here
are GPLv3: complete source is in this repo, the upstream `LICENSE` and `NOTICE`
are preserved, and changes are visible in git history. Upstream attribution is
carried by those files, not by visibility — a private copy would have credited
upstream just as well.

The intended use is to build our own products to sell later. GPLv3 does not
extend to output merely because a GPL-covered program produced it; the factory
is tooling, not the product. Two boundaries still apply:

- Conveying the factory code itself — shipping it to a customer or embedding it
  in a product — keeps the GPLv3 obligations above: complete corresponding
  source, GPLv3 license, preserved notices and changed-file markings, no
  additional restrictions. Charging for it is allowed; proprietary closure is
  not.
- If generated output contains literal chunks of the GPL factory scripts or
  prompts, those chunks remain GPL. Review before shipping such output.

If selling the factory itself ever becomes the goal, switch to a clean-room
rewrite: implement this document's *behaviour* with our own orchestrator,
agents and scripts, not upstream's *expression*. Ideas and workflows are not
copyrightable; specific files are.

This is engineering guidance, not legal advice. A commercial launch should be
reviewed by counsel.

## 11. Decision

**Port it.** The port is ~1.5–3 days, and the deterministic spine means most of
it is packaging and testing rather than new logic.

**Adopt it on a project only with a real gate and a deliberately narrow remit.**
The value depends entirely on `factory/checks.sh` and on accepting that the
human stays in the merge path for anything that changes runtime behaviour.
