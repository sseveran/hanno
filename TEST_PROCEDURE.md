# Hanno + Claude Code Integration — Manual Test Procedure

This procedure validates the end-to-end integration between Hanno and Claude Code hooks.
Run these tests in order — later tests depend on state from earlier ones.

## Prerequisites

```bash
# Ensure hanno CLI is available
uv run hanno --help

# Start with a clean state
rm -f ~/.hanno/hanno.db ~/.hanno/active_session.json
```

---

## 1. Automated Tests

Run the full test suite first to confirm everything passes:

```bash
uv run pytest packages/ -q
```

Expected: 201 tests pass, 0 failures.

---

## 2. Hook Config Generation

```bash
uv run hanno session hooks
```

Expected: JSON output with hooks for `SessionStart`, `PreCompact`, `PostToolUse`, `Stop`, `SessionEnd`. `PostToolUse` and `Stop` should have `"async": true`.

---

## 3. Session Lifecycle — Auto-Create

Simulate a Claude Code session using piped JSON on stdin.

### 3a. SessionStart (startup)

```bash
echo '{"session_id":"test-001","source":"startup","cwd":"/tmp/test","hook_event_name":"SessionStart"}' \
  | uv run hanno session start
```

Expected output: `[Hanno] Created run <RUN_ID> (type: claude_session). Step <STEP_ID> active.`

Save the run ID:
```bash
RUN_ID=$(cat ~/.hanno/active_session.json | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")
echo "Run ID: $RUN_ID"
```

### 3b. Verify state file

```bash
cat ~/.hanno/active_session.json | python3 -m json.tool
```

Expected: JSON with `run_id`, `step_run_id`, `session_id: "test-001"`, `started_at`.

### 3c. Verify run was created

```bash
uv run hanno run show $RUN_ID
```

Expected: Run with status `running`, type `claude_session`.

### 3d. Verify step was created

```bash
uv run hanno step list $RUN_ID
```

Expected: 1 step named `session` with status `running`.

---

## 4. Tool Use Logging

### 4a. Log a Bash command

```bash
echo '{"session_id":"test-001","hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"npm test"}}' \
  | uv run hanno session log-tool
```

### 4b. Log a Write

```bash
echo '{"session_id":"test-001","hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"/src/main.py"}}' \
  | uv run hanno session log-tool
```

### 4c. Verify filtered tool is skipped (Read)

```bash
echo '{"session_id":"test-001","hook_event_name":"PostToolUse","tool_name":"Read","tool_input":{"file_path":"/src/main.py"}}' \
  | uv run hanno session log-tool
```

### 4d. Verify notes in event log

```bash
uv run hanno event list $RUN_ID
```

Expected: 2 `note` events — one with "Bash: npm test", one with "Write: /src/main.py". No note for Read.

---

## 5. Stop Logging

```bash
echo '{"session_id":"test-001","hook_event_name":"Stop","stop_hook_active":false}' \
  | uv run hanno session log-stop
```

```bash
uv run hanno event list $RUN_ID
```

Expected: Additional `note` event with "Agent finished responding".

---

## 6. Compaction (PreCompact + SessionStart compact)

### 6a. Create a fake transcript

```bash
echo '{"messages":[{"role":"user","content":"fix the bug"},{"role":"assistant","content":"done"}]}' > /tmp/test-transcript.json
```

### 6b. PreCompact

```bash
echo '{"session_id":"test-001","hook_event_name":"PreCompact","trigger":"auto","transcript_path":"/tmp/test-transcript.json"}' \
  | uv run hanno session snapshot
```

Expected: `[Hanno] Transcript saved. New step <NEW_STEP_ID> started (post-compaction).`

### 6c. Verify step rotation

```bash
uv run hanno step list $RUN_ID
```

Expected: 2 steps — first `succeeded` with summary "Session compacted (auto)", second `running`.

### 6d. Verify transcript artifact

```bash
uv run hanno artifact list $RUN_ID
```

Expected: 1 artifact with kind `transcript`.

### 6e. SessionStart (compact) — should NOT create a new step

```bash
echo '{"session_id":"test-001","source":"compact","hook_event_name":"SessionStart"}' \
  | uv run hanno session start
```

Expected: `[Hanno] Resumed (post-compaction) run <RUN_ID> ...`

```bash
uv run hanno step list $RUN_ID
```

Expected: Still 2 steps (not 3).

---

## 7. Session End

### 7a. Create a final transcript

```bash
echo '{"messages":[{"role":"user","content":"fix the bug"},{"role":"assistant","content":"all done"}]}' > /tmp/test-transcript-final.json
```

### 7b. SessionEnd

```bash
echo '{"session_id":"test-001","hook_event_name":"SessionEnd","reason":"logout","transcript_path":"/tmp/test-transcript-final.json"}' \
  | uv run hanno session end
```

Expected: `[Hanno] Session ended. Step <STEP_ID> completed.`

### 7c. Verify state file cleared

```bash
test -f ~/.hanno/active_session.json && echo "FAIL: state file still exists" || echo "OK: state file cleared"
```

### 7d. Verify final state

```bash
uv run hanno step list $RUN_ID
```

Expected: 2 steps, both `succeeded`.

```bash
uv run hanno artifact list $RUN_ID
```

Expected: 2 artifacts (pre-compaction transcript + final transcript).

---

## 8. Resume by HANNO_RUN_ID

Start a new session on the same run:

```bash
echo '{"session_id":"test-002","source":"startup","hook_event_name":"SessionStart"}' \
  | HANNO_RUN_ID=$RUN_ID uv run hanno session start
```

Expected: `[Hanno] Resumed run <RUN_ID> ...`

```bash
uv run hanno step list $RUN_ID
```

Expected: 3 steps (2 completed from before + 1 new running).

Clean up:
```bash
echo '{"session_id":"test-002","hook_event_name":"SessionEnd","reason":"logout"}' \
  | uv run hanno session end
```

---

## 9. Resume by HANNO_REF

### 9a. Create a run with an external ref

```bash
uv run hanno run create pr_review --title "Review PR #42" --ref "github:pr:org/repo#42" --json
```

Save the ID:
```bash
PR_RUN_ID=<copy id from output>
```

### 9b. Start session with HANNO_REF

```bash
echo '{"session_id":"test-003","source":"startup","hook_event_name":"SessionStart"}' \
  | HANNO_REF="github:pr:org/repo#42" uv run hanno session start
```

Expected: `[Hanno] Resumed run <PR_RUN_ID> ...` (should find the existing run).

### 9c. Verify it attached to the right run

```bash
cat ~/.hanno/active_session.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['run_id'])"
```

Expected: Matches `PR_RUN_ID`.

Clean up:
```bash
echo '{"hook_event_name":"SessionEnd","reason":"logout"}' | uv run hanno session end
```

### 9d. HANNO_REF with no existing run creates one

```bash
echo '{"session_id":"test-004","source":"startup","hook_event_name":"SessionStart"}' \
  | HANNO_REF="jira:ticket:PROJ-999" uv run hanno session start
```

Expected: `[Hanno] Created run <NEW_ID> ...`

```bash
uv run hanno run find --ref "jira:ticket:PROJ-999"
```

Expected: 1 run found.

Clean up:
```bash
echo '{"hook_event_name":"SessionEnd","reason":"logout"}' | uv run hanno session end
```

---

## 10. Run Find

```bash
uv run hanno run find --ref "github:pr:org/repo#42"
```

Expected: Table showing the PR review run.

```bash
uv run hanno run find --ref "github:pr:nonexistent"
```

Expected: "No runs found."

---

## 11. Custom HANNO_LOG_TOOLS

```bash
# Start a session
echo '{"session_id":"test-005","source":"startup"}' | uv run hanno session start --json
CUSTOM_RUN=$(cat ~/.hanno/active_session.json | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")

# With custom filter, Read should be logged, Bash should not
echo '{"tool_name":"Read","tool_input":{"file_path":"/f.py"}}' \
  | HANNO_LOG_TOOLS="Read,Grep" uv run hanno session log-tool

echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' \
  | HANNO_LOG_TOOLS="Read,Grep" uv run hanno session log-tool

uv run hanno event list $CUSTOM_RUN
```

Expected: 1 note for Read, none for Bash.

Clean up:
```bash
echo '{"hook_event_name":"SessionEnd","reason":"logout"}' | uv run hanno session end
```

---

## 12. Live Integration (optional)

If you want to test with actual Claude Code:

1. Get the hook config:
   ```bash
   uv run hanno session hooks > /tmp/hanno-hooks.json
   ```

2. Merge into your `.claude/settings.json` (the `hooks` key).

3. Start a Claude Code session and check:
   ```bash
   cat ~/.hanno/active_session.json | python3 -m json.tool
   uv run hanno run list
   ```

4. Do some work (write files, run commands), then check events:
   ```bash
   RUN_ID=<from above>
   uv run hanno event list $RUN_ID
   ```

5. Run `/compact` in Claude Code, then verify:
   ```bash
   uv run hanno step list $RUN_ID
   uv run hanno artifact list $RUN_ID
   ```

6. Exit Claude Code (`/exit` or Ctrl+C), then verify:
   ```bash
   uv run hanno step list $RUN_ID
   uv run hanno artifact list $RUN_ID
   test -f ~/.hanno/active_session.json && echo "state file still exists" || echo "state file cleared"
   ```

---

## Cleanup

```bash
rm -f /tmp/test-transcript.json /tmp/test-transcript-final.json
rm -f ~/.hanno/hanno.db ~/.hanno/active_session.json
```
