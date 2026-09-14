# M09. Audit / Local Analysis Store

## 1. 책임

모든 분석·Patch·검증·승인 상태를 추적 가능하게 기록하고,
Web Control Plane에서 이력을 조회할 수 있도록 로컬 저장소에 보관한다.

---

# 2. Audit Log

Audit는 마지막에 한 번 작성하지 않는다.

**event-by-event append-only**를 기본으로 한다.
`REQUEST_RECEIVED` 등 초기 Audit은 request id / type / target reference 중심으로 최소화하며, raw source / 전체 prompt / credential 가능 문자열을 기본 payload로 그대로 저장하지 않는다.

---

# 3. Audit Events

예:

```text
REQUEST_RECEIVED
IDENTITY_RESOLVED
ACL_CHECKED
GRAPH_REFRESHED
PATCH_PROPOSED
PROPOSAL_BASE_STALE
PATCH_REVISION_CREATED
PATCH_STATE_CHANGED
PATCH_APPLY_FAILED
PRELIMINARY_RISK_RECALCULATED
PRE_APPLY_GUARDRAIL_BLOCKED
POST_APPLY_GUARDRAIL_BLOCKED
PATCH_APPLIED_TO_WORKTREE
FINAL_RISK_CALCULATED
VERIFICATION_PLAN_CREATED
COMMAND_EXECUTED
VERIFICATION_RESULT
USER_APPROVED
APPROVAL_BINDING_RECORDED
PATCH_ARTIFACT_STORED
APPLY_RECOVERY_STARTED
APPLY_ATTEMPT_STARTED
APPLY_CRASH_RECONCILED
APPLY_LOCK_UNAVAILABLE
SOURCE_CONSISTENCY_MATCH
SOURCE_CONSISTENCY_MISMATCH
TARGET_PREIMAGE_MISMATCH
PATCH_APPLY_TO_REPOSITORY_FAILED
APPLY_RESULT_MISMATCH
REPOSITORY_REMEDIATION_REQUIRED
WORKTREE_BASELINE_MUTATION_DETECTED
VERIFICATION_SOURCE_MUTATION_DETECTED
SENSITIVE_FILE_EXCEPTION_USED
VERIFICATION_NOT_APPLICABLE_DECIDED
SANDBOX_SENSITIVE_RUNTIME_READ_USED
CANONICAL_CHANGE_SET_CREATED
CANONICAL_CHANGE_SET_UNAVAILABLE
WORKTREE_PREPARATION_BLOCKED
STALE_LOCK_RECOVERED
ORPHAN_WORKTREE_CLEANED
ORPHAN_SANDBOX_CLEANED
SAFE_GIT_POLICY_BLOCKED
VERIFICATION_BASIS_RECORDED
VERIFICATION_BASIS_MISMATCH
APPLY_AUTHORIZATION_DENIED
APPROVAL_AUTHORIZATION_REVOKED
APPROVAL_REVALIDATION_REQUIRED
CRITICAL_PERSISTENCE_FAILED
TEST_SELECTION_INTEGRITY_VIOLATION
SENSITIVE_EXECUTION_RESULT_CLASSIFIED
SENSITIVE_CONTEXT_RESULT_CLASSIFIED
SENSITIVE_PROVENANCE_PROPAGATED
SENSITIVE_DECLASSIFICATION_AUTHORIZED
SENSITIVE_REMOTE_PUBLISH_AUTHORIZED
VERIFICATION_BASIS_COMPATIBILITY_DECIDED
REMOTE_OPERATION_STARTED
REMOTE_OPERATION_SUCCEEDED
REMOTE_OPERATION_FAILED
REMOTE_OPERATION_RECONCILED
PATCH_APPLIED_TO_REPOSITORY
```

---

# 4. PATCH_STATE_CHANGED

모든 lifecycle 상태 전이를 generic event로 저장한다.

예:

```text
event_type: PATCH_STATE_CHANGED
patch_id: patch_123
from: VERIFYING
to: FAILED
reason: related_test_failed
timestamp: ...
```

기록 대상 예:

```text
PROPOSED → APPLIED_TO_WORKTREE
PROPOSED → PATCH_APPLY_FAILED
APPLIED_TO_WORKTREE → VERIFYING
VERIFYING → VERIFIED
VERIFYING → FAILED
VERIFYING → INCONCLUSIVE
VERIFIED → APPROVED
APPROVED → VERIFIED   # Approval binding invalidated, Verification은 유효
APPROVED → APPLIED
APPROVED → STALE_VERIFICATION

# `PROPOSAL_BASE_STALE`은 lifecycle state가 아니라 Proposal base mismatch Audit event이며, 기존 `PROPOSED` revision을 새 base에 적용하지 않는다. 새 base에서 proposal을 재생성하면 새 revision / hash를 생성한다.
# `APPLY_LOCK_UNAVAILABLE`은 lifecycle state가 아니라 일시적 Apply 실행 오류 / Audit event다.
# lock 획득 실패만으로 APPROVED 상태를 변경하지 않는다.
```

---

# 5. PATCH_REVISION_CREATED

Patch가 변경되면 새 revision 이벤트를 기록한다.

```text
patch_id
revision
previous_patch_hash
new_patch_hash
reason
timestamp
```

---

# 6. Audit Metadata

포함:

- user identifier
- identity source / session reference
- repository
- branch
- base commit
- head state / Git operation state
- request type
- target symbol
- request intent id / protected request reference-or-hash
- acceptance criteria / Verification mapping reference + mapping hash/version
- evidence type
- risk rule version / threshold version
- Verification environment / toolchain fingerprint
- change plan ID
- patch ID / revision / patch hash / patch artifact schema version / generator provenance
- proposal base repository / branch / commit / source snapshot hash / preliminary risk reference
- final diff hash / change-set schema version
- approval binding (`verification_result_id / verification_basis_id / request_intent_id / approver_user_id / approval_policy_version` 또는 동등한 승인 권한 기준 포함)
- approval evidence reference / immutable approval-evidence hash / displayed-summary basis reference
- guardrail / command / sandbox policy version
- Verification `NOT_APPLICABLE` reason / evidence / decision authority
- Sensitive File exception operation (`read-context / runtime-read / modify / declassify / remote-publish`) / scope / policy version
- sensitive execution / context-derived result classification / `sensitive_provenance` lineage / protected artifact reference / access scope
- Verification security exception / NOT_APPLICABLE / policy backward-compatibility decision reference
- apply attempt id / pre-apply source hash / expected post-apply result hash
- post-apply result integrity evidence
- optional remote_operation_id / explicit remote intent-or-workflow authorization reference / provider target / exact applied result binding / remote result reference
- test / benchmark result
- test / benchmark evidence provenance 및 baseline/post-patch selection reference
- final decision
- application result

---

# 7. Local Analysis Store

성공 상태만 저장하지 않는다.

```text
PROPOSED
APPLIED_TO_WORKTREE
PATCH_APPLY_FAILED
VERIFYING
VERIFIED
FAILED
INCONCLUSIVE
APPROVED
STALE_VERIFICATION
APPLIED
```

모든 lifecycle 상태와 Verification Result를 저장한다.

추가로 Web Control Plane과 재현 가능한 분석을 위해 다음 Evidence / 상태를 로컬 저장소에서 조회 가능하게 유지한다.

```text
Repository Context
Graph / Graph Freshness
Impact / Risk Result
Benchmark / Profiler Result
Local-Only / Security Runtime Status
```

---

# 8. Patch Storage 최소화

전체 source 또는 불필요한 민감 코드 보관을 피한다.

필요 시 다음 중심으로 저장한다.

```text
patch_id
revision
patch_hash
final_diff_hash
canonical patch artifact 또는 durable local artifact reference
metadata
risk
verification result / verification_basis_id
audit event reference
```

`VERIFIED` revision은 프로세스 재시작 이후에도 동일한 검증 대상 Patch를 식별하고 재적용할 수 있도록 canonical patch artifact 또는 동등한 durable local artifact reference를 유지해야 한다.
해당 artifact의 durable persistence와 hash / revision integrity가 확인되기 전에는 해당 revision을 사용자 Approval 대상으로 노출하지 않는다. Artifact persistence가 실패하면 `CRITICAL_PERSISTENCE_FAILED`로 fail-closed 처리하고 Approval / Apply로 진행하지 않는다.

필수 원칙:

- artifact는 `patch_id / revision / patch_hash / patch_artifact_schema_version / final_diff_hash / change_set_schema_version`과 무결성 연결을 유지한다.
- hash만 저장하고 실제 verified Patch를 복원할 수 없는 상태를 허용하지 않는다.
- Patch artifact는 Audit event payload와 분리된 보호된 Local Store에 보관할 수 있어야 한다.
- Patch artifact 접근에는 해당 Repository의 현재 ACL / RBAC를 적용한다.
- approval / apply / recovery 시 과거 ACL snapshot만 신뢰하지 않고 현재 authorization 결과를 별도 Audit에 연결할 수 있어야 한다.
- Sensitive File modification exception 또는 `sensitive_provenance`를 포함하는 Patch artifact는 민감 artifact로 분류하고 Web / Audit payload에 raw content를 노출하지 않는다. Declassification decision이 있더라도 Audit lineage는 유지한다.
- sensitive execution 또는 sensitive context-derived result raw payload를 보존해야 하는 경우 일반 Audit event payload와 분리된 protected Local Store / ACL을 적용하며, Web에는 권한 없는 raw result를 노출하지 않는다.
- 전체 Repository source snapshot을 불필요하게 보관하지 않는다.
- 보존 기간 / 암호화 방식 / 실제 artifact storage 제품은 상세설계에서 확정한다.

구체 보관정책은 상세설계에서 확정한다.

---

# 9. 장애 내구성 요구

프로세스가 중간에 종료되어도 이미 기록된 Audit Event는 유지되어야 한다.

Lifecycle state transition과 그 상태를 설명하는 필수 Audit Event는 서로 모순된 상태로 영구 저장되지 않도록 atomic transaction 또는 crash-recoverable mechanism으로 일관성을 보장해야 한다.
Verification 완료 시 최종 CheckResult / Verification Result / finalized `verification_basis_id`의 무결성 연결과 `VERIFYING → VERIFIED|FAILED|INCONCLUSIVE` state transition도 crash-consistent하게 저장한다. Basis 또는 Result durable persistence가 실패하면 `VERIFIED` authority를 노출하지 않는다.

필수 원칙:

- state transition이 commit되었는데 대응 Audit Event가 영구 유실되거나, Audit Event만 commit되고 state가 영구적으로 이전 상태에 남는 상태를 허용하지 않는다.
- 저장소 재시작 시 append-only event history와 current lifecycle state를 검증 / 복구할 수 있어야 한다.
- Apply / Verification 등 중요 전이는 idempotency key 또는 동등한 중복 방지 기준을 가질 수 있어야 한다.
- Repository Apply 같은 외부 filesystem side effect는 실행 전에 durable Apply Intent를 기록하고 durable commit 성공을 확인한 뒤에만 side effect를 시작한다. 재시작 시 pre-apply / expected-post-apply state를 비교해 미완료 attempt를 reconcile할 수 있어야 한다.
- Approval / Apply / Verification authority를 형성하는 필수 state / Audit / artifact persistence가 disk-full, I/O error, transaction failure 등으로 durable하게 기록되지 못하면 해당 권한 상승 또는 side effect를 fail-closed로 중단한다. `CRITICAL_PERSISTENCE_FAILED` 또는 동등한 event를 가능한 범위에서 기록하고, durable 상태가 복구되기 전 자동으로 Apply를 계속하지 않는다.
- 복원된 verified Patch artifact는 사용 전에 저장된 `patch_hash / revision / patch_artifact_schema_version / final_diff_hash / change_set_schema_version`와 무결성을 재검증한다.

---

# 10. Web 제공 정보

- Repository / Graph / Graph Freshness History
- Patch History
- Proposal base stale / Apply Recovery / remediation required / post-apply integrity / optional Remote Operation history
- Verification History
- failed/inconclusive/stale history
- Risk
- Benchmark
- Audit timeline
- Security status reference

---

# 11. 성공 기준

- 요청부터 적용까지 추적할 수 있다.
- User Approval이 정확한 Patch revision / hash / Verification Result / Verification Basis에 바인딩되었는지 추적할 수 있다.
- lifecycle 상태 변화가 append-only로 기록된다.
- Patch revision 변경 이력을 추적할 수 있다.
- VERIFIED Patch revision을 프로세스 재시작 이후에도 동일 artifact로 식별 / 복원할 수 있다.
- Approval eligibility 전에 canonical verified Patch artifact의 durable persistence / integrity를 확인할 수 있다.
- APPROVED 상태의 Apply Recovery / lock 실패 / Repository Apply 실패 / crash reconciliation / result mismatch / remediation 이력을 Audit에서 추적할 수 있다.
- lifecycle state와 대응 Audit Event가 crash 이후에도 일관되게 복구될 수 있다.
- Approval / Verification / Apply authority를 형성하는 critical persistence가 실패하면 side effect를 fail-closed로 차단할 수 있다.
- Repository / Graph / Graph Freshness evidence를 Web에서 조회할 수 있다.
- 실패 / stale 이력도 Web에서 조회할 수 있다.
- Verification Basis / request intent / acceptance mapping / risk rule / policy mismatch와 Sensitive execution / context-derived result의 제한된 metadata를 추적할 수 있다.
