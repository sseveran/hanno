"""Named SQL constants for the SQLite storage backend."""

# Workspaces
INSERT_WORKSPACE = """
INSERT INTO workspaces (id, title, status, external_refs_json,
    labels_json, metadata_json, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_WORKSPACE = "SELECT * FROM workspaces WHERE id = ?"

UPDATE_WORKSPACE = """
UPDATE workspaces SET title = ?, status = ?, external_refs_json = ?, labels_json = ?,
    metadata_json = ?, updated_at = ?
WHERE id = ?
"""

# Workspace repos
INSERT_WORKSPACE_REPO = """
INSERT INTO workspace_repos (id, workspace_id, vcs, display_name, canonical_remote,
    local_path, default_branch, metadata_json, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_WORKSPACE_REPO = "SELECT * FROM workspace_repos WHERE id = ?"

UPDATE_WORKSPACE_REPO = """
UPDATE workspace_repos SET vcs = ?, display_name = ?, canonical_remote = ?,
    local_path = ?, default_branch = ?, metadata_json = ?, updated_at = ?
WHERE id = ?
"""

# Tasks
INSERT_TASK = """
INSERT INTO tasks (id, workspace_id, title, status, external_refs_json,
    labels_json, metadata_json, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_TASK = "SELECT * FROM tasks WHERE id = ?"

UPDATE_TASK = """
UPDATE tasks SET title = ?, status = ?, external_refs_json = ?, labels_json = ?,
    metadata_json = ?, updated_at = ?
WHERE id = ?
"""

# Task repo links
INSERT_TASK_REPO_LINK = """
INSERT INTO task_repo_links (id, task_id, workspace_repo_id, created_at)
VALUES (?, ?, ?, ?)
"""

# Runs
INSERT_RUN = """
INSERT INTO runs (id, workspace_id, task_id, workspace_repo_id, run_type, status, title,
    external_refs_json, labels_json, metadata_json, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_RUN = "SELECT * FROM runs WHERE id = ?"

UPDATE_RUN = """
UPDATE runs SET workspace_id = ?, task_id = ?, workspace_repo_id = ?, status = ?, title = ?,
    external_refs_json = ?, labels_json = ?, metadata_json = ?, updated_at = ?
WHERE id = ?
"""

# Events
INSERT_EVENT = """
INSERT INTO events (id, run_id, sequence, kind, actor_json, payload_json,
    step_run_id, parent_event_id, trace_id, span_id, timestamp)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_EVENT = "SELECT * FROM events WHERE id = ?"

# Steps
INSERT_STEP_RUN = """
INSERT INTO step_runs (id, run_id, step_name, status, iteration, parent_step_run_id,
    started_at, ended_at, summary, metadata_json, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_STEP_RUN = "SELECT * FROM step_runs WHERE id = ?"

UPDATE_STEP_RUN = """
UPDATE step_runs SET status = ?, started_at = ?, ended_at = ?, summary = ?, metadata_json = ?
WHERE id = ?
"""

# Edges
INSERT_EDGE = """
INSERT INTO edges (id, run_id, from_step_run_id, to_step_run_id, kind, metadata_json)
VALUES (?, ?, ?, ?, ?, ?)
"""

# State versions
INSERT_STATE_VERSION = """
INSERT INTO state_versions (id, run_id, sequence, prev_state_version_id, state_ref,
    state_hash, actor_json, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

# Artifacts
INSERT_ARTIFACT = """
INSERT INTO artifacts (id, run_id, step_run_id, kind, uri, content_hash, size,
    content_type, name, metadata_json, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_ARTIFACT = "SELECT * FROM artifacts WHERE id = ?"

# Approvals
INSERT_APPROVAL = """
INSERT INTO approvals (id, run_id, step_run_id, status, authority, resource,
    criteria_json, requested_by_json, resolved_by_json, reason, requested_at, resolved_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_APPROVAL = "SELECT * FROM approvals WHERE id = ?"

UPDATE_APPROVAL = """
UPDATE approvals SET status = ?, resolved_by_json = ?, reason = ?, resolved_at = ?
WHERE id = ?
"""

# Leases
INSERT_LEASE = """
INSERT INTO leases (id, run_id, lease_token, owner_json, purpose, acquired_at, expires_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

SELECT_LEASE = "SELECT * FROM leases WHERE id = ?"

DELETE_LEASE = "DELETE FROM leases WHERE id = ?"

DELETE_EXPIRED_LEASES = "DELETE FROM leases WHERE expires_at < datetime('now')"

# Sequence counter
UPSERT_SEQUENCE = """
INSERT INTO sequence_counters (run_id, current_seq) VALUES (?, 1)
ON CONFLICT(run_id) DO UPDATE SET current_seq = current_seq + 1
"""

SELECT_SEQUENCE = "SELECT current_seq FROM sequence_counters WHERE run_id = ?"
