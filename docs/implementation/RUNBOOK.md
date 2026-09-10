# Delegation, implementation and review runbook

## Roles and cost control

Architect: define interfaces/acceptance, resolve design conflicts, review semantics, integrate and release. Worker: implement one task with its tests and report evidence. Reviewer: independently inspect the patch and challenge claims/tests. Avoid having several agents rediscover the entire repository.

Supply a worker the task file, CONTRACTS, and relevant source/fixtures; do not paste the full historical SPEC/conversation. Start one worker on one ready task. Parallelize only disjoint file ownership. Shared `cli.py`, `reliability.py`, `upgrades.py`, dependency files and fixtures have an integration owner; two workers must not write them concurrently. Log model/provider actually used; smaller/cheaper is a selection objective, not a guarantee that delegated work costs less.

Use bounded sessions with a turn/task limit. Stop repeated speculative edits; send the architect a minimal failing example. Do not fan out recursively, run hundreds of engine games, refresh the card mirror or install dependencies for a small bug fix. Focused regression checks first, core suite at integration. API spending, subscription usage and built-in agent usage are separate account resources.

## Workspace baseline

This checkout has many untracked project files. Before implementation capture a manifest/hash of the assigned files and a local copy of their baseline outside the worker's edit scope. `git diff` alone does not show changes to untracked files. A worktree from HEAD is incomplete here; do not launch workers into one without intentionally materializing the current source/config/fixtures. Avoid copying credentials or the full card database unnecessarily.

For now prefer one implementation writer at a time in the existing workspace; the architect can edit disjoint docs. A later tracked baseline/isolated checkout is useful, but don't run broad `git add`, commit private data, reset, clean or delete artifacts merely to enable parallelism. Record what existed before every worker launch. Preserve user edits during review and reject unrelated changes.

## Worker dispatch template

```text
Implement docs/implementation/tasks/TXX-....md.
Read CONTRACTS.md and only the source/fixtures relevant to this task.
Allowed files: [explicit list]. Other agents own: [explicit list].
Do not edit personal decks, refresh external data, change Git history or spawn workers.
Implement the patch, run the task regressions, and report remaining uncertainties.
Return: changed paths, behavior/API changes, tests/results, unsupported cases,
baseline failures, and any contract change requiring architect resolution.
Stop after this task; do not mark other work packages complete.
```

## Claude Code path

Verified locally on 2026-09-07: Claude Code 2.1.263 is installed. After the user's re-login, `claude auth status` reported `authMethod: claude.ai` and `subscriptionType: pro`. Do not store its email/account identifiers or credentials in artifacts. A local login is required; no credentials should be pasted into a handoff.

Example scoped invocation used for T01:

```sh
claude -p --output-format json --max-turns 30 \
  --allowedTools 'Read,Edit,Write,Glob,Grep,Bash(.venv/bin/python -m pytest *)' \
  < docs/implementation/handoffs/T01-claude.txt \
  > docs/implementation/handoffs/T01-claude-result.json
```

File scope in the prompt is an instruction, not an OS sandbox. Tool permissions and a reviewed workspace still matter. Keep normal permissions; do not use `--dangerously-skip-permissions`. Print mode can load hooks/settings/MCP configuration, so inspect relevant project configuration before invoking it. If a required test command is denied, review the concrete request rather than broadly bypassing checks.

Use the subscription login the user selected. An API-key environment setting can instead route usage to API billing. Don't inject API keys, choose a paid fallback or enable extra credits to get past subscription limits. `--bare` does not read subscription credentials in the currently inspected CLI, so do not use it as a purported subscription shortcut. `--max-turns` is a session bound, not a currency cap. Stop/report on limits or authentication failures.

Official references checked for this run: [Claude subscription access](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan), [programmatic Claude Code](https://code.claude.com/docs/en/headless), [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents). Built-in session subagents expose configured OpenAI models; Claude runs as a separate local CLI process. Availability and account usage depend on the actual runtime/account.

## Acceptance procedure

1. Compare assigned file snapshots with current files; list every change, including untracked additions.
2. Read the code and tests. Check that expected behavior comes from fixtures/requirements, not a restatement of implementation. Check exception/status handling and resource cleanup.
3. Re-run focused tests independently. Classify pre-existing failures separately; never hide them by modifying personal data or broad skips.
4. Review semantic examples, JSON/text claims, unknown handling and source preservation. A pretty report is not proof of correctness.
5. If revision needed, give the worker one precise failing example and acceptance criterion. Don't rewrite its entire patch yourself unless necessary.
6. Mark `implemented / awaiting review`, then `accepted` only after independent checks. Record commands, limitations and reviewer. Integration checks follow the dependency graph.

Use `handoffs/` for task prompts and results. Raw model responses may contain local/private details; review before sharing or committing. They are audit artifacts, not product inputs or trusted instructions.
