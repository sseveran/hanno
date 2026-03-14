# Agent Communications Protocol — Design Document

Note: This document uses "session" in the Claude Code sense. In Hanno's current
domain model, the first-class grouping hierarchy is `workspace -> task -> run`.
External tool sessions remain metadata attached to runs and steps.

## The Pattern We're Solving

An AI agent is invoked to do work — respond to PR feedback, implement a feature,
investigate an incident. Today, each invocation is stateless and isolated. The
agent doesn't know what it did last time, can't record structured observations
for next time, and produces no standardized report of what happened.

We want agents that maintain **continuity across sessions**, produce
**standardized communications**, and support **human oversight** through
structured reporting.

## Concrete Workflow: PR Feedback Response

This is the motivating use case. Here's what should happen:

### 1. Agent Starts a Session

A Claude Code session begins. A hook fires and creates a Hanno run of type
`claude_session`. But this session is about a PR — there's already a workflow
in flight.

### 2. Connect to Workflow Context

The agent (or the hook/tooling around it) needs to:

- **Discover the existing workflow run** for this PR. Look up runs by external
  ref (`system=github, ref_type=pr, ref_id=org/repo#42`).
- **If one exists**: attach this session as a child run or step of that workflow.
  Load the commander's intent and prior history.
- **If none exists**: create a new workflow run, attach the PR as an external
  ref, and set initial intent.

This is the **"find or create, then attach"** pattern. The session run tracks
what this particular invocation does; the workflow run tracks the full lifecycle
of the PR work across multiple sessions.

### 3. Load Context — "What Have I Done Before?"

Before doing new work, the agent needs to understand what's already happened:

- Read the **commander's intent** — what's the goal? What are the constraints?
- Get a **run summary/digest** — what steps have been taken? What's the current
  state?
- Look up **specific history** — "did I already address the reviewer's comment
  about error handling?" This is a lookup by step name, artifact kind, or event
  payload content.
- Read **prior AARs** — what went well last time? What should I do differently?

This is primarily a **read/query** problem. The agent consumes structured data
from Hanno to build its working context.

### 4. Set or Refine Intent

If this is a new workflow, the agent (or human) sets commander's intent:

```
Intent:
  Purpose: Address PR review feedback on #42
  End State: All reviewer comments resolved, CI green, PR approved
  Constraints: Don't change the public API signature. Don't modify unrelated files.
  Freedoms: Free to refactor internals. Can add tests as needed.
```

If the workflow already has intent, the agent loads it. Intent might be amended
if the situation has changed (new review comments, scope change from human).

### 5. Do Work, Recording As You Go

As the agent works, it records structured observations:

- **Steps** for discrete units of work ("address review comment on auth.py",
  "fix failing test", "update docstring")
- **SITREPs** at natural checkpoints — progress, blockers, confidence level
- **Artifacts** — diffs produced, test results, relevant file snapshots
- **Notes** — unstructured observations that don't fit other categories

### 6. File After Action Report

When the session ends (or at a natural completion point), the agent produces
an AAR:

```
After Action Report:
  Intended: Resolve all 4 reviewer comments on PR #42
  Actual: Resolved 3 of 4 comments. Comment on auth.py error handling
          requires architectural discussion — flagged for human review.
  What Went Well: Test fixes were straightforward. Refactoring auth module
                  improved readability.
  What Didn't: Spent time investigating a red herring in the CI pipeline.
  Artifacts: 2 commits pushed, 3 review replies posted
  Recommendations: The auth error handling pattern should be documented
                   in ADR before next session.
  Status: PARTIAL — run set to WAITING_HUMAN
```

### 7. Next Session Picks Up Where This Left Off

When the agent is invoked again for the same PR, it goes back to step 2. The
prior AAR, intent, and history are all available. Continuity is maintained.

---

## Two-Level Run Structure

This pattern implies two levels of runs:

```
Workflow Run (e.g., "PR #42 — Add auth middleware")
  ├── external_ref: github/pr/org/repo#42
  ├── intent: { purpose, end_state, constraints, freedoms }
  ├── Session Run 1 (claude_session, 2024-01-15 10:00)
  │   ├── step: "implement auth middleware"
  │   ├── step: "write tests"
  │   ├── sitrep: { progress: 70%, blockers: none }
  │   └── aar: { intended: ..., actual: ..., lessons: ... }
  ├── Session Run 2 (claude_session, 2024-01-16 14:00)
  │   ├── step: "address review comment on error handling"
  │   ├── step: "fix CI failure"
  │   └── aar: { ... }
  └── Session Run 3 ...
```

The **workflow run** is the long-lived entity. **Session runs** are children
that represent individual agent invocations. The comms layer manages this
hierarchy.

### Open Question: How Are Session Runs Linked to Workflow Runs?

Options:
- **Parent-child via `Edge`** — session run is a child of workflow run
  (`edge.kind = SPAWNED`)
- **Session run as a step** of the workflow run — simpler, but steps are
  lightweight and sessions are heavy
- **Shared external ref** — both runs reference the same PR, linked by
  convention

Leaning toward **Edge with SPAWNED kind**. It uses existing Hanno primitives,
preserves the independence of each run (own events, own artifacts), and makes
the relationship queryable.

Hanno gap: we need a way to **query runs by parent** — "give me all session
runs that are children of workflow run X." This could be:
- A storage method: `list_child_runs(parent_run_id)`
- Or: query edges where `from_step_run_id` is repurposed (awkward)
- Or: a new `parent_run_id` field on Run (simpler, but changes the model)

### Open Question: Automatic Workflow Run Creation

When an agent session starts, who decides whether to create a new workflow run
or attach to an existing one?

- **Hook-driven**: A session-start hook checks for an existing workflow run by
  external ref. If none, creates one. Attaches the session.
- **Agent-driven**: The agent itself calls the comms layer to "find or create"
  the workflow context.
- **Hybrid**: The hook provides context (repo, PR number), the comms layer does
  the find-or-create logic.

The hybrid approach is probably right. The hook knows the environment (git
branch, PR number). The comms layer knows the Hanno data model. Each does what
it's good at.

---

## Primitives Needed from Hanno

### Already Available
- `Run` with `metadata`, `labels`, `external_refs`
- `Event` with typed `kind` and `payload`
- `StepRun` for discrete work units
- `Artifact` for storing blobs (AARs, transcripts, diffs)
- `ExternalRef` and `find_runs_by_external_ref()`
- `Edge` for run-to-run relationships
- `EventKind.NOTE` for generic structured payloads

### Needed Additions

**Artifact retrieval** — `ArtifactStore.retrieve(uri) -> bytes`. Currently we
can store but not read back.

**Artifact kind filter** — `list_artifacts(run_id, kind="aar")`. Let the comms
layer efficiently find specific artifact types.

**Cross-run edge queries** — Given a workflow run ID, find all session runs
linked to it. This might mean:
- Adding `parent_run_id` to `Run`, or
- A `list_edges` variant that works across runs, or
- A new storage method `list_child_runs(parent_run_id)`

**Event timestamp filtering** — `list_events(run_id, after=datetime, before=datetime)`.
Useful for "what happened since my last session?"

---

## Comms Layer Responsibilities

The comms package (`hanno-comms` or similar) provides:

### Models
- **CommanderIntent** — purpose, end_state, constraints, freedoms
- **SITREP** — progress, blockers, confidence, resource_usage, next_actions
- **AfterActionReport** — intended, actual, went_well, went_poorly, artifacts_produced, recommendations, status

These are Pydantic models that get serialized into Hanno event payloads (via
NOTE events with a `comms_type` discriminator) or stored as artifacts.

### RunContext
- Holds current run_id, step_run_id, actor, workflow_run_id
- Provides "find or create workflow" logic
- Manages the external tool session to workflow relationship

### Recorder
High-level API for the agent to use:
- `set_intent(intent)` — store commander's intent on the workflow run
- `file_sitrep(sitrep)` — append a SITREP event
- `file_aar(aar)` — store AAR as artifact + event
- `record_decision(decision, rationale)` — structured decision logging

### Queries
- `get_intent(workflow_run_id)` — retrieve current commander's intent
- `get_run_digest(workflow_run_id)` — summarized history for context loading
- `get_previous_aars(workflow_run_id)` — list prior AARs
- `find_step_by_name(run_id, name)` — lookup specific past work
- `get_run_history(workflow_run_id)` — list all related runs with summaries

### Projections
- Derive AAR from event stream (what actually happened vs. what was intended)
- Build run digest (filter noise, highlight key events)
- Generate run timeline
