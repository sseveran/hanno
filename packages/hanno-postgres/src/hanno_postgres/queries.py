"""Named SQL constants for the Postgres storage backend."""

# Workspaces
INSERT_WORKSPACE = """
INSERT INTO workspaces (id, title, status, external_refs_json,
    labels_json, metadata_json, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""

SELECT_WORKSPACE = "SELECT * FROM workspaces WHERE id = $1"

UPDATE_WORKSPACE = """
UPDATE workspaces SET title = $1, status = $2, external_refs_json = $3, labels_json = $4,
    metadata_json = $5, updated_at = $6
WHERE id = $7
"""

# Workspace repos
INSERT_WORKSPACE_REPO = """
INSERT INTO workspace_repos (id, workspace_id, vcs, display_name, canonical_remote,
    local_path, default_branch, metadata_json, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
"""

SELECT_WORKSPACE_REPO = "SELECT * FROM workspace_repos WHERE id = $1"

UPDATE_WORKSPACE_REPO = """
UPDATE workspace_repos SET vcs = $1, display_name = $2, canonical_remote = $3,
    local_path = $4, default_branch = $5, metadata_json = $6, updated_at = $7
WHERE id = $8
"""

# Tasks
INSERT_TASK = """
INSERT INTO tasks (id, workspace_id, title, status, external_refs_json,
    labels_json, metadata_json, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""

SELECT_TASK = "SELECT * FROM tasks WHERE id = $1"

UPDATE_TASK = """
UPDATE tasks SET title = $1, status = $2, external_refs_json = $3, labels_json = $4,
    metadata_json = $5, updated_at = $6
WHERE id = $7
"""

# Task repo links
INSERT_TASK_REPO_LINK = """
INSERT INTO task_repo_links (id, task_id, workspace_repo_id, created_at)
VALUES ($1, $2, $3, $4)
"""

# Runs
INSERT_RUN = """
INSERT INTO runs (id, workspace_id, task_id, workspace_repo_id, run_type, status, title,
    external_refs_json, labels_json, metadata_json, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
"""

SELECT_RUN = "SELECT * FROM runs WHERE id = $1"

UPDATE_RUN = """
UPDATE runs SET workspace_id = $1, task_id = $2, workspace_repo_id = $3, status = $4,
    title = $5, external_refs_json = $6, labels_json = $7, metadata_json = $8, updated_at = $9
WHERE id = $10
"""

# Events
INSERT_EVENT = """
INSERT INTO events (id, run_id, sequence, kind, actor_json, payload_json,
    step_run_id, parent_event_id, trace_id, span_id, timestamp)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""

SELECT_EVENT = "SELECT * FROM events WHERE id = $1"

# Steps
INSERT_STEP_RUN = """
INSERT INTO step_runs (id, run_id, step_name, status, iteration, parent_step_run_id,
    started_at, ended_at, summary, metadata_json, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""

SELECT_STEP_RUN = "SELECT * FROM step_runs WHERE id = $1"

UPDATE_STEP_RUN = """
UPDATE step_runs SET status = $1, started_at = $2, ended_at = $3, summary = $4, metadata_json = $5
WHERE id = $6
"""

# Edges
INSERT_EDGE = """
INSERT INTO edges (id, run_id, from_step_run_id, to_step_run_id, kind, metadata_json)
VALUES ($1, $2, $3, $4, $5, $6)
"""

# State versions
INSERT_STATE_VERSION = """
INSERT INTO state_versions (id, run_id, sequence, prev_state_version_id, state_ref,
    state_hash, actor_json, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""

# Artifacts
INSERT_ARTIFACT = """
INSERT INTO artifacts (id, run_id, step_run_id, kind, uri, content_hash, size,
    content_type, name, metadata_json, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""

SELECT_ARTIFACT = "SELECT * FROM artifacts WHERE id = $1"

# Approvals
INSERT_APPROVAL = """
INSERT INTO approvals (id, run_id, step_run_id, status, authority, resource,
    criteria_json, requested_by_json, resolved_by_json, reason, requested_at, resolved_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
"""

SELECT_APPROVAL = "SELECT * FROM approvals WHERE id = $1"

UPDATE_APPROVAL = """
UPDATE approvals SET status = $1, resolved_by_json = $2, reason = $3, resolved_at = $4
WHERE id = $5
"""

# Leases
INSERT_LEASE = """
INSERT INTO leases (id, run_id, lease_token, owner_json, purpose, acquired_at, expires_at)
VALUES ($1, $2, $3, $4, $5, $6, $7)
"""

SELECT_LEASE = "SELECT * FROM leases WHERE id = $1"

DELETE_LEASE = "DELETE FROM leases WHERE id = $1"

DELETE_EXPIRED_LEASES = "DELETE FROM leases WHERE expires_at < NOW() RETURNING id"

# Sequence counter
UPSERT_SEQUENCE = """
INSERT INTO sequence_counters (run_id, current_seq) VALUES ($1, 1)
ON CONFLICT(run_id) DO UPDATE SET current_seq = sequence_counters.current_seq + 1
RETURNING current_seq
"""
