#!/usr/bin/env bash
# Static gate for the OpenCode software factory.
#
# Run from anywhere: bash factory/checks.sh (or ./factory/checks.sh).
# Exit 0 = all checks pass, 1 = at least one check failed.
#
# This repo is the FACTORY; the repo being checked is the PROJECT. The default
# project is ../project next to this repo; override with FACTORY_PROJECT.
#
# This gate is deliberately static: it runs in a worktree with no host or
# deploy access. Anything that needs runtime verification stays a human step,
# governed by the project's own rules.
#
# Environment:
#   FACTORY_PROJECT project to check (default: ../project)
#   FACTORY_BASE    branch to diff against for shellcheck scoping (default: trunk)
#   FACTORY_REQUIRE_SHELLCHECK=1  fail if shellcheck is not installed
set -uo pipefail

FACTORY_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${FACTORY_PROJECT:-$(cd "$FACTORY_HOME/.." && pwd)/project}"
if [[ ! -d "$PROJECT" ]]; then
  printf 'FAIL  project not found: %s (set FACTORY_PROJECT)\n' "$PROJECT"
  exit 1
fi
BASE="${FACTORY_BASE:-trunk}"
cd "$PROJECT" || exit 2

failures=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }
skip() { printf 'SKIP  %s\n' "$*"; }
note() { printf '      %s\n' "$*"; }

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is required"
  exit 1
fi
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  fail "PyYAML is required (python3 -m pip install pyyaml)"
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/extracted"

# --- 1. Shell syntax: every tracked *.sh -----------------------------------
sh_files=()
while IFS= read -r -d '' f; do
  sh_files+=("$f")
done < <(find . -path ./.git -prune -o -name '*.sh' -type f -print0 | sort -z)

syntax_bad=0
for f in "${sh_files[@]}"; do
  if ! out=$(bash -n "$f" 2>&1); then
    fail "shell syntax: $f"
    note "$out"
    syntax_bad=1
  fi
done
if ((syntax_bad == 0)); then
  pass "shell syntax (${#sh_files[@]} scripts)"
fi

# --- 2. Embedded shell syntax, YAML, JSON, cross-file consistency ----------
# These need a YAML parser, so they live in one Python pass. The pass also
# extracts embedded shell blocks to $tmp/extracted for the lint step below and
# writes $tmp/owners.tsv mapping each block back to its source file.
PROJECT="$PROJECT" GATE_TMP="$tmp" BASE="$BASE" python3 <<'PY'
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter

import yaml

project = os.environ["PROJECT"]
tmp = os.environ["GATE_TMP"]
os.chdir(project)
nfail = 0


def ok(msg):
    print("PASS  " + msg)


def bad(msg, detail=""):
    global nfail
    print("FAIL  " + msg)
    if detail:
        for line in str(detail).splitlines():
            print("      " + line)
    nfail += 1


def check(name, fn):
    """Run a named assertion; fn returns a list of errors (empty means pass)."""
    try:
        errs = fn()
        if errs:
            suffix = f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""
            bad(name + ": " + errs[0] + suffix)
            for err in errs[1:6]:
                print("      - " + err)
        else:
            ok(name)
    except Exception as exc:  # a missing/malformed structure is a gate failure
        bad(name, f"{type(exc).__name__}: {exc}")


def repo_glob(pattern):
    return sorted(
        p for p in glob.glob(pattern, recursive=True)
        if "/.git/" not in p and not p.startswith(".git/")
    )


def load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def shell_blocks(doc):
    """Shell snippets from one cloud-init doc: *.sh write_files, shell-shebang
    write_files, and string runcmd entries. Python write_files are excluded."""
    blocks = []
    for wf in doc.get("write_files", []) or []:
        content = wf.get("content", "") or ""
        first = content.lstrip().splitlines()[0] if content.strip() else ""
        if str(wf.get("path", "")).endswith(".sh") or re.search(
            r"(?:^|/)(?:ba|z|k)?sh\b", first
        ):
            blocks.append(content)
    for cmd in doc.get("runcmd", []) or []:
        if isinstance(cmd, str):
            blocks.append("#!/bin/bash\n" + cmd + "\n")
    return blocks


base_branch = os.environ.get("BASE", "trunk")
base_available = subprocess.run(
    ["git", "rev-parse", "--verify", base_branch], capture_output=True
).returncode == 0

# Extract each block and mark whether it differs from the base branch. Lint is
# enforced per changed block, so a config-only edit to a YAML file does not turn
# that file's legacy shell warnings into gate failures.
yaml_paths = repo_glob("**/*.yaml") + repo_glob("**/*.yml")
extracted = []  # (destination, owning YAML path, changed flag)
for path in yaml_paths:
    try:
        doc = load_yaml(path)
    except Exception:
        # check_yaml() below reports the parse error; do not crash extraction.
        continue
    blocks = shell_blocks(doc)
    remaining = Counter()
    if base_available:
        shown = subprocess.run(
            ["git", "show", f"{base_branch}:{path}"], capture_output=True, text=True
        )
        if shown.returncode == 0:
            try:
                remaining = Counter(shell_blocks(yaml.safe_load(shown.stdout) or {}))
            except Exception:
                remaining = Counter()
    for body in blocks:
        name = f"embedded_{len(extracted):04d}.sh"
        dest = os.path.join(tmp, "extracted", name)
        with open(dest, "w") as fh:
            fh.write(body)
        changed = 0
        if base_available:
            if remaining.get(body, 0):
                remaining[body] -= 1
            else:
                changed = 1
        extracted.append((dest, path, changed))

with open(os.path.join(tmp, "owners.tsv"), "w") as fh:
    for dest, owner, changed in extracted:
        fh.write(f"{os.path.basename(dest)}\t{owner}\t{changed}\n")


def check_embedded_syntax():
    errs = []
    for dest, owner, _ in extracted:
        result = subprocess.run(["bash", "-n", dest], capture_output=True, text=True)
        if result.returncode:
            line = result.stderr.strip().splitlines()[-1]
            errs.append(f"{owner} ({os.path.basename(dest)}): {line}")
    return errs


check(f"embedded shell syntax ({len(extracted)} blocks)", check_embedded_syntax)

json_paths = repo_glob("**/*.json")


def check_yaml():
    errs = []
    for path in yaml_paths:
        try:
            yaml.safe_load(open(path))
        except Exception as exc:
            errs.append(f"{path}: {exc}")
    return errs


def check_json():
    errs = []
    for path in json_paths:
        try:
            json.load(open(path))
        except Exception as exc:
            errs.append(f"{path}: {exc}")
    return errs


check(f"YAML parse ({len(yaml_paths)} files)", check_yaml)
check(f"JSON parse ({len(json_paths)} files)", check_json)

sys.exit(nfail)
PY
python_rc=$?
failures=$((failures + python_rc))

# --- 3. Lint: shellcheck, enforced only on changed shell
# Projects carry known shellcheck warnings in older shell scripts and embedded
# snippets; those are advisory so the base branch stays green. A changed *.sh
# file, or a changed embedded shell block, must be clean at warning severity.
if command -v shellcheck >/dev/null 2>&1; then
  declare -A changed_set=()
  if git rev-parse --verify "$BASE" >/dev/null 2>&1; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && changed_set["$line"]=1
    done < <({ git diff --name-only "$BASE" -- .; git ls-files --others --exclude-standard -- .; } | sort -u)
  else
    skip "shellcheck changed-file scope (base '$BASE' not found; all findings advisory)"
  fi

  lint_targets=("${sh_files[@]}")
  for dest in "$tmp"/extracted/*.sh; do
    [[ -e "$dest" ]] && lint_targets+=("$dest")
  done

  lint_failed=0
  advisory=0
  for f in "${lint_targets[@]}"; do
    findings=$(shellcheck -f gcc -S warning "$f" 2>/dev/null) || true
    [[ -z "$findings" ]] && continue

    changed=""
    key="${f#./}"  # find emits ./ prefixed paths; git does not
    if [[ "$f" == "$tmp"/extracted/* ]]; then
      changed=$(awk -F '\t' -v n="$(basename "$f")" '$1 == n { print $3; exit }' "$tmp/owners.tsv")
    elif [[ -n "${changed_set[$key]:-}" ]]; then
      changed=1
    fi
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      if [[ "$changed" == "1" ]]; then
        fail "shellcheck: $line"
        lint_failed=1
      else
        advisory=$((advisory + 1))
      fi
    done <<< "$findings"
  done
  if ((lint_failed == 0)); then
    pass "shellcheck (${#changed_set[@]} changed files clean; $advisory pre-existing findings advisory)"
  fi
else
  if [[ "${FACTORY_REQUIRE_SHELLCHECK:-0}" == "1" ]]; then
    fail "shellcheck is required (FACTORY_REQUIRE_SHELLCHECK=1) but not installed"
  else
    skip "shellcheck (not installed; set FACTORY_REQUIRE_SHELLCHECK=1 to enforce)"
  fi
fi

if ((failures == 0)); then
  echo "OK: all checks passed"
else
  echo "FAILED: $failures check(s) failed"
fi
exit $((failures == 0 ? 0 : 1))
