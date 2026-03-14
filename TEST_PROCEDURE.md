# Hanno + Claude Code Integration - Manual Test Procedure

This procedure validates the end-to-end integration between Hanno and Claude Code
hooks after the `workspace -> task -> run` refactor.

Note: Claude's hook payload still contains a `session_id`. That is the external
tool session identifier, not a Hanno domain object.

## Prerequisites

```bash
# Ensure the CLI is available
uv run hanno --help

# Start with a clean local state
rm -f ~/.hanno/hanno.db ~/.hanno/active_task.json
```

## 1. Automated Tests

Run the non-Postgres suite first:

```bash
uv run pytest packages/hanno-core packages/hanno-cli packages/hanno-mcp -q
```

Optional, if Docker is available locally:

```bash
uv run pytest packages/hanno-postgres/tests/test_postgres_storage.py -q
```

## 2. Create a Workspace and Task

```bash
WORKSPACE_ID=$(
  uv run hanno workspace create --title "Manual Integration Workspace" --json \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])"
)

TASK_ID=$(
  uv run hanno task create --workspace-id "$WORKSPACE_ID" --title "Hook Lifecycle" --json \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])"
)

echo "Workspace: $WORKSPACE_ID"
echo "Task: $TASK_ID"
```

## 3. Hook Config Generation

```bash
uv run hanno task hooks
```

Expected: JSON output with hooks for `SessionStart`, `PreCompact`, `PostToolUse`,
`Stop`, and `SessionEnd`. `PostToolUse` and `Stop` should be async.

## 4. Task Lifecycle - Explicit Workspace and Task

### 4a. Start a hook-driven run

```bash
echo '{"session_id":"test-001","source":"startup","hook_event_name":"SessionStart"}' \
  | HANNO_WORKSPACE_ID="$WORKSPACE_ID" HANNO_TASK_ID="$TASK_ID" uv run hanno task start
```

Expected output: `[Hanno] Created run <RUN_ID> ... workspace=<WORKSPACE_ID> task=<TASK_ID>.`

Save the run ID:

```bash
RUN_ID=$(
  python3 -c "import json, pathlib; print(json.loads(pathlib.Path.home().joinpath('.hanno/active_task.json').read_text())['run_id'])"
)
echo "Run ID: $RUN_ID"
```

### 4b. Verify the active state file

```bash
python3 -m json.tool ~/.hanno/active_task.json
```

Expected: JSON with `workspace_id`, `task_id`, `run_id`, `step_run_id`, and
`tool_session_id`.

### 4c. Verify the run

```bash
uv run hanno run show "$RUN_ID"
```

Expected: Run is `running` and shows the workspace ID and task ID.

### 4d. Verify the initial step

```bash
uv run hanno step list "$RUN_ID"
```

Expected: 1 running step named `task-step`.

## 5. Tool Use Logging

### 5a. Log a Bash command

```bash
echo '{"session_id":"test-001","hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"npm test"}}' \
  | uv run hanno task log-tool
```

### 5b. Log a Write

```bash
echo '{"session_id":"test-001","hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"/src/main.py"}}' \
  | uv run hanno task log-tool
```

### 5c. Verify filtered tool is skipped

```bash
echo '{"session_id":"test-001","hook_event_name":"PostToolUse","tool_name":"Read","tool_input":{"file_path":"/src/main.py"}}' \
  | uv run hanno task log-tool
```

### 5d. Verify note events

```bash
uv run hanno event list "$RUN_ID"
```

Expected: 2 `note` events, one for the Bash command and one for the Write.

## 6. Stop Logging

```bash
echo '{"session_id":"test-001","hook_event_name":"Stop","stop_hook_active":false}' \
  | uv run hanno task log-stop
```

```bash
uv run hanno event list "$RUN_ID"
```

Expected: Additional `note` event with `Agent finished responding`.

## 7. Compaction

### 7a. Create a fake transcript

```bash
echo '{"messages":[{"role":"user","content":"fix the bug"},{"role":"assistant","content":"done"}]}' \
  > /tmp/test-transcript.json
```

### 7b. PreCompact

```bash
echo '{"session_id":"test-001","hook_event_name":"PreCompact","trigger":"auto","transcript_path":"/tmp/test-transcript.json"}' \
  | uv run hanno task snapshot
```

Expected: `[Hanno] Transcript saved. New step <STEP_ID> started (post-compaction).`

### 7c. Verify step rotation

```bash
uv run hanno step list "$RUN_ID"
```

Expected: 2 steps. The first is `succeeded` with summary `Task step compacted (auto)`.
The second is `running`.

### 7d. Verify transcript artifact

```bash
uv run hanno artifact list "$RUN_ID"
```

Expected: 1 artifact with kind `transcript`.

### 7e. Post-compaction resume should not create another step

```bash
echo '{"session_id":"test-001","source":"compact","hook_event_name":"SessionStart"}' \
  | uv run hanno task start
```

Expected: `[Hanno] Resumed (post-compaction) run <RUN_ID> ...`

```bash
uv run hanno step list "$RUN_ID"
```

Expected: Still 2 steps.

## 8. End the Active Task Run

### 8a. Create a final transcript

```bash
echo '{"messages":[{"role":"user","content":"fix the bug"},{"role":"assistant","content":"all done"}]}' \
  > /tmp/test-transcript-final.json
```

### 8b. SessionEnd

```bash
echo '{"session_id":"test-001","hook_event_name":"SessionEnd","reason":"logout","transcript_path":"/tmp/test-transcript-final.json"}' \
  | uv run hanno task end
```

Expected: `[Hanno] Task run ended. Step <STEP_ID> completed.`

### 8c. Verify the state file cleared

```bash
test -f ~/.hanno/active_task.json && echo "FAIL: state file still exists" || echo "OK: state file cleared"
```

### 8d. Verify final run state

```bash
uv run hanno step list "$RUN_ID"
uv run hanno artifact list "$RUN_ID"
```

Expected: Both steps are complete and there are 2 transcript artifacts.

## 9. Resume an Existing Run with HANNO_RUN_ID

```bash
echo '{"session_id":"test-002","source":"startup","hook_event_name":"SessionStart"}' \
  | HANNO_RUN_ID="$RUN_ID" uv run hanno task start
```

Expected: `[Hanno] Resumed run <RUN_ID> ...`

```bash
uv run hanno step list "$RUN_ID"
```

Expected: 3 steps, with the newest step running.

Clean up:

```bash
echo '{"session_id":"test-002","hook_event_name":"SessionEnd","reason":"logout"}' \
  | uv run hanno task end
```

## 10. Resolve a Task by HANNO_TASK_REF

Create a new workspace for a ref-driven task:

```bash
REF_WORKSPACE_ID=$(
  uv run hanno workspace create --title "Ref Workspace" --json \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])"
)
```

Start a task using an external ref:

```bash
echo '{"session_id":"test-003","source":"startup","hook_event_name":"SessionStart"}' \
  | HANNO_WORKSPACE_ID="$REF_WORKSPACE_ID" HANNO_TASK_REF="github:pr:org/repo#42" uv run hanno task start
```

Save the created task and run IDs:

```bash
REF_TASK_ID=$(
  python3 -c "import json, pathlib; print(json.loads(pathlib.Path.home().joinpath('.hanno/active_task.json').read_text())['task_id'])"
)
REF_RUN_ID=$(
  python3 -c "import json, pathlib; print(json.loads(pathlib.Path.home().joinpath('.hanno/active_task.json').read_text())['run_id'])"
)

echo "Task: $REF_TASK_ID"
echo "Run:  $REF_RUN_ID"
```

Verify the task and run:

```bash
uv run hanno task show "$REF_TASK_ID"
uv run hanno run show "$REF_RUN_ID"
```

Expected: The task exists in `REF_WORKSPACE_ID`, and the run is attached to that
workspace and task.

Clean up:

```bash
echo '{"session_id":"test-003","hook_event_name":"SessionEnd","reason":"logout"}' \
  | uv run hanno task end
```

## 11. Optional: Auto-Create Workspace from Repo Context

From inside a git checkout with a configured `origin` remote:

```bash
echo "{\"session_id\":\"test-004\",\"source\":\"startup\",\"cwd\":\"$PWD\",\"hook_event_name\":\"SessionStart\"}" \
  | HANNO_TASK_REF="jira:ticket:PROJ-999" uv run hanno task start
```

Expected: If the repo is not yet attached to a workspace, Hanno creates a
workspace, creates a workspace repo record from the git remote, creates a task
for `PROJ-999`, and starts the run.

## 12. Live Integration (Optional)

1. Generate hook config:

```bash
uv run hanno task hooks > /tmp/hanno-hooks.json
```

2. Merge the `hooks` block into `.claude/settings.json`.

3. Start Claude Code and verify:

```bash
python3 -m json.tool ~/.hanno/active_task.json
uv run hanno run list
```

4. Do some work, then inspect the run:

```bash
RUN_ID=<from above>
uv run hanno event list "$RUN_ID"
uv run hanno step list "$RUN_ID"
uv run hanno artifact list "$RUN_ID"
```

5. Exit Claude Code and verify the state file is removed:

```bash
test -f ~/.hanno/active_task.json && echo "state file still exists" || echo "state file cleared"
```

## Cleanup

```bash
rm -f /tmp/test-transcript.json /tmp/test-transcript-final.json
rm -f ~/.hanno/hanno.db ~/.hanno/active_task.json
```
