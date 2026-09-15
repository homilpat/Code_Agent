CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    os_principal TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0, 1))
);
CREATE TABLE repositories (
    repository_id TEXT PRIMARY KEY,
    common_dir TEXT UNIQUE NOT NULL,
    common_identity TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE repository_roots (
    root_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(repository_id),
    canonical_root TEXT UNIQUE NOT NULL,
    root_identity TEXT NOT NULL,
    git_dir TEXT NOT NULL,
    git_identity TEXT NOT NULL
);
CREATE TABLE permissions (
    user_id TEXT NOT NULL REFERENCES users(user_id),
    repository_id TEXT NOT NULL REFERENCES repositories(repository_id),
    permission TEXT NOT NULL,
    PRIMARY KEY(user_id, repository_id, permission)
);
CREATE TABLE request_intents (
    request_intent_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(repository_id),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    request_hash TEXT NOT NULL,
    request_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(repository_id),
    relative_path TEXT UNIQUE NOT NULL,
    content_hash TEXT NOT NULL,
    size INTEGER NOT NULL CHECK(size >= 0),
    classification TEXT NOT NULL CHECK(classification IN ('NORMAL', 'SENSITIVE', 'PROTECTED')),
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE patches (
    patch_id TEXT PRIMARY KEY,
    request_intent_id TEXT NOT NULL REFERENCES request_intents(request_intent_id),
    repository_id TEXT NOT NULL REFERENCES repositories(repository_id)
);
CREATE TABLE patch_revisions (
    patch_id TEXT NOT NULL REFERENCES patches(patch_id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    patch_hash TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    proposal_base_commit TEXT NOT NULL,
    proposal_source_snapshot_hash TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN
      ('PROPOSED','APPLIED_TO_WORKTREE','PATCH_APPLY_FAILED','VERIFYING','VERIFIED',
       'FAILED','INCONCLUSIVE','APPROVED','STALE_VERIFICATION','APPLIED')),
    final_diff_hash TEXT,
    verification_result_id TEXT,
    verification_basis_id TEXT,
    verification_plan_json TEXT,
    PRIMARY KEY(patch_id, revision)
);
CREATE TABLE verification_results (
    result_id TEXT PRIMARY KEY,
    basis_id TEXT UNIQUE NOT NULL,
    patch_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    basis_hash TEXT NOT NULL,
    basis_json TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('VERIFIED','FAILED','INCONCLUSIVE')),
    FOREIGN KEY(patch_id, revision) REFERENCES patch_revisions(patch_id, revision)
);
CREATE TABLE audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1,
    repository_id TEXT REFERENCES repositories(repository_id),
    user_id TEXT REFERENCES users(user_id),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    previous_event_digest TEXT,
    event_digest TEXT UNIQUE NOT NULL,
    CHECK((sequence = 1) = (previous_event_digest IS NULL))
);
CREATE TABLE operations (
    idempotency_key TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE graph_snapshots (
    graph_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(repository_id),
    source_snapshot_hash TEXT NOT NULL,
    graph_hash TEXT NOT NULL,
    builder_version TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(repository_id, graph_hash)
);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'Audit events are append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'Audit events are append-only'); END;
CREATE TRIGGER result_no_update BEFORE UPDATE ON verification_results
BEGIN SELECT RAISE(ABORT, 'Verification results are immutable'); END;
CREATE TRIGGER result_no_delete BEFORE DELETE ON verification_results
BEGIN SELECT RAISE(ABORT, 'Verification results are immutable'); END;
PRAGMA user_version = 2;
