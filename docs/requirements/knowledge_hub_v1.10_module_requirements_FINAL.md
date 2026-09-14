# Knowledge Hub Code Intelligence — v1.10 모듈별 요구사항 최종 통합본

본 문서는 v1.10의 사용자 기능 / Local-Only / 승인 / 검증 intent를 구현 모듈별로 재분류하고, 실제 구현에서 해당 intent가 우회되지 않도록 필요한 Derived Safety / Integrity Requirements를 함께 명시한다.

> 기준 문서: `knowledge_hub_code_intelligence_requirements_v1.10.md`  
> 목적: 사용자 기능 범위를 임의로 확장하지 않으면서, TOCTOU / crash recovery / evidence integrity / sandbox escape / secret exposure / unsafe Git execution / policy drift 등의 실패 모드를 fail-closed로 처리할 수 있는 구현 요구사항을 확정한다.

Derived Safety Requirements는 새로운 제품 기능을 추가하기 위한 것이 아니라 원 v1.10의 기능·보안 의도를 재현 가능하고 안전하게 구현하기 위한 파생 제약이다. DB 제품, IPC, exact API schema, exact container flags 등 구체 기술 선택은 Architecture / Detailed Design에서 확정한다.

---

# 1. 모듈 구성

```text
M01 CLI / Identity / Access
M02 Repository Context / Code Graph
M03 Query Planner / Code Understanding
M04 Impact / Risk Analysis
M05 Patch Lifecycle / Worktree / Source Consistency
M06 Sandbox / Command Policy / agent_rule
M07 Verification / Profiling / Benchmark
M08 Local-Only Security
M09 Audit / Local Analysis Store
M10 Web Control Plane
M11 Integration / Acceptance / Traceability
```

---

# 2. 전체 실행 흐름

```text
Developer
  ↓
M01 Identity + Canonical Repository Identity
  ↓
M01 Repository ACL / RBAC
  ↓
M02 Repository Context / Source Snapshot / Graph Freshness
  ↓
M03 Trusted Request Intent + Query Planner + Acceptance Criteria
  ↓
M04 Impact / Preliminary Risk
  ↓
[PERFORMANCE / OPTIMIZE 필요 시]
M05 Safe Git Worktree Materialization Integrity
  ↓
M06 Command Policy / Sandbox Baseline
  ↓
M07 Runtime Evidence
  ↓
M04 Preliminary Risk Refresh
  ↓
M05 Canonical Patch Proposal + Proposal Base Binding
  ↓
Proposal Base Consistency Check
  ├─ STALE → PROPOSAL_BASE_STALE / Re-analysis + New Revision / Apply BLOCK
  └─ MATCH
          ↓
M06 Pre-Apply Guardrail
  ↓
M05 Quota-bound / Alias-safe Patch Apply in Safe Git Worktree
  ├─ fail → PATCH_APPLY_FAILED → STOP
  └─ success → APPLIED_TO_WORKTREE
          ↓
M05 Canonical Actual Change Set
  ├─ INCOMPLETE → CANONICAL_CHANGE_SET_UNAVAILABLE → Verification BLOCK
  └─ COMPLETE
          ↓
M06 Post-Apply Diff Guardrail
  ↓
M04 Final Change Risk + Risk Rule / Threshold Version
  ↓
M07 Verification Plan + Acceptance Criteria / Test / Toolchain Provenance
  ↓
M06 Command Policy / Sandbox
  ↓
M07 Test / Static / Benchmark + Source Integrity Check
  ├─ mutation → Evidence 폐기 / exact Patch snapshot 복원 / 재검증
  └─ unchanged
          ↓
M09 Final CheckResult + finalized Verification Basis durable linkage
  ├─ persistence fail → CRITICAL_PERSISTENCE_FAILED / Approval authority BLOCK
  ├─ FAILED
  ├─ INCONCLUSIVE
  └─ VERIFIED
          ↓
M09 Canonical Verified Patch Artifact Durable Persistence / Integrity
  ├─ persistence fail → Approval BLOCK
  └─ durable
          ↓
Current Verification Basis / Security Exception / Authorization Compatibility
          ↓
Informed User Approval bound to exact Request Intent / Patch / Verification / Approval Evidence / Approval Policy Basis
          ↓
M09 Approval Binding + APPROVED transition atomic/durable persistence
  ├─ persistence fail → VERIFIED 유지 / Apply BLOCK
  └─ APPROVED
          ↓
M05 Repository Serialization + Source / Policy / Authorization / Approval Binding Recheck
  ├─ LOCK FAIL → APPLY_LOCK_UNAVAILABLE / APPROVED 유지
  ├─ SOURCE/POLICY MISMATCH → STALE_VERIFICATION
  ├─ Approval invalid → VERIFIED / re-approval required
  └─ MATCH
          ↓
M09 Durable Apply Attempt Intent
  ├─ persistence fail → Apply side effect BLOCK
  └─ durable
          ↓
M05 Verified Canonical Artifact 기반 Safe-Git / Alias-safe Local Apply
          ↓
Post-Apply Result Integrity Check
  ├─ MATCH → APPLIED
  ├─ atomic fail without mutation → APPROVED 유지 / Apply Recovery
  └─ MISMATCH / partial / unknown → STALE_VERIFICATION / remediation required

Lock은 획득한 모든 exit path에서 release한다.
Apply 직후 crash는 pre-apply / expected-post-apply hash로 reconcile하며 중복 Apply를 금지한다.
remediation required 상태에서는 clean / consistent Repository 복구 전 자동 Retry / Re-analysis / Re-verification / Recovery / Remote Operation을 진행하지 않는다.
Remote Operation은 `APPLIED` exact result에서 materialized된 hash-bound immutable source만 대상으로 하며 current ACL, M08 internal allowlist, sensitive provenance / declassification / remote-publish policy를 다시 적용한다.
```

모든 lifecycle / security / verification / recovery / remote-operation 이벤트는 M09에 crash-consistent하게 저장되며 M10은 current ACL과 protected-result policy를 적용해 조회한다.

---

# 3. 권장 코드 디렉터리 매핑

```text
blogProject/
├── backend-spring/
├── frontend-nextjs/
├── rag-fastapi/
├── code-agent/
│   ├── cli/                  # M01
│   ├── identity/             # M01
│   ├── repository/           # M02
│   ├── adapters/
│   │   ├── potpie/           # M02
│   │   ├── static_analysis/  # M02/M03/M04
│   │   └── profiler/         # M07
│   ├── planner/              # M03
│   ├── explain/              # M03
│   ├── impact/               # M04
│   ├── risk/                 # M04
│   ├── patch/                # M05
│   ├── worktree/             # M05
│   ├── sandbox/              # M06
│   ├── harness/              # M06
│   ├── verification/         # M07
│   ├── benchmark/            # M07
│   ├── security/             # M08
│   ├── audit/                # M09
│   └── store/                # M09
└── docker-compose.yml
```

Web Control Plane은 기존 `frontend-nextjs / backend-spring / rag-fastapi`에 Code Intelligence 조회 / 시각화 기능을 추가하는 방식으로 연결한다.

---

# 4. 모듈 간 핵심 계약

| From | To | 핵심 전달 데이터 |
|---|---|---|
| M01 | M02 | user_id, repository_id, canonical_repository_root, command, target |
| M02 | M03 | repository_context, source_snapshot_reference, graph evidence, graph freshness, nested-repository / filesystem-boundary evidence |
| M03 | M04 | request_intent_id, resolved_query, target_entities, task, acceptance_criteria / mapping reference |
| M03 | M05 | request_intent_id, resolved modification intent, target entities, acceptance context |
| M04 | M05 | impact_result, preliminary_risk, risk_rule_version, threshold_version |
| M03 | M07 | request_intent_id, acceptance_criteria_mapping, protected request reference/hash |
| M08 | M06 | sensitive-file / sensitive-provenance / declassification policy decision, scoped exception, security policy version |
| M05 | M06 | proposed_patch, canonical target paths, policy_context, sensitive_provenance metadata |
| M06 | M05 | pre_apply_guardrail_decision, block_reason, guardrail policy version |
| M05 | M06 | canonical_actual_change_set, changed paths/types, patch_revision, change_set_schema_version |
| M06 | M05/M04 | post_apply_guardrail_decision, policy/security findings, policy version |
| M05 | M04 | canonical_actual_change_set, final_diff_hash, changed_symbols |
| M04 | M07 | final_change_risk, risk_rule_version, threshold_version |
| M07 | M06 | verification_plan, acceptance_criteria_mapping, test/toolchain provenance requirement, allowed execution request |
| M06 | M07 | command result, test/profiler/static result, environment/dependency provenance, sandbox/profile/policy version |
| M07 | M09 | CheckResult set, VerificationResult, finalized verification_basis_id, evidence provenance |
| M02 | M09 | repository context, source snapshot, graph/freshness evidence |
| M04 | M09 | impact/risk result, risk rule / threshold version |
| M05/M06/M07 | M09 | proposal-base binding/provenance, lifecycle, guardrail, change-set, verification, apply/recovery/integrity event |
| M08 | M09 | Local-Only/security status, sensitive provenance, scoped exception/declassification/remote-publish decision |
| M09 | M01/M05 | verified artifact integrity, approval binding/policy, approval-evidence hash/reference, critical persistence, recovery metadata |
| M09 | M10 | graph/risk/benchmark/patch/audit/security/remediation/provenance history |

---

# 5. 변경 / 동결 원칙

이 패키지는 v1.10의 사용자 기능 범위와 핵심 보안 / 검증 intent를 유지한다. 본문의 Derived Safety Requirements는 원 요구사항을 안전하게 실현하기 위한 fail-closed 제약이며, 다음 구체 설계는 Architecture / Detailed Design에서 확정한다.

- 실제 DB 제품(SQLite/PostgreSQL 등)
- CLI 프레임워크
- IPC 방식(localhost API / Unix socket / direct mode)
- Risk Score exact 가중치 / 공식
- Potpie 내부 구현 세부
- JWT 발급 방식
- Web UI exact layout
- 구체 API URL / request schema
- 구체 Sandbox runtime / container / VM 제품과 exact isolation flag
- hash algorithm / canonical serialization의 구체 구현(단, versioning / integrity semantics는 본 요구사항을 만족해야 함)
- exact policy DSL / exception approval UI / declassification workflow 구현

---

# M01. CLI / Identity / Repository Access

## 1. 책임

개발자가 사용하는 기본 작업면을 제공하고,
Repository 접근 전에 사용자 Identity와 권한을 확립한다.

본 모듈은 코드 분석 자체를 수행하지 않는다.
분석 요청을 안전하게 다음 모듈로 전달하는 진입점이다.

---

# 2. 핵심 요구사항

## M01-FR-01. CLI 명령

다음 명령을 제공한다.

```bash
kh status
kh explain <target>
kh impact <target>
kh modify "<request>"
kh profile <target>
kh optimize <target>
kh verify
kh apply
kh history
```

### 명령 의미

- `kh status`
  - Repository root
  - branch
  - commit
  - dirty state
  - Local-Only 상태
  - Graph 최신성 등 현재 상태 조회

- `kh explain`
  - 파일 / 클래스 / 함수 역할 설명 요청

- `kh impact`
  - 변경 영향 / Risk 분석 요청

- `kh modify`
  - 변경 계획과 Patch 생성 요청
  - 원본 Repository 즉시 수정 금지

- `kh profile`
  - CPU / Memory / runtime 분석 요청

- `kh optimize`
  - Evidence 기반 성능 최적화 요청

- `kh verify`
  - Temporary Worktree / Sandbox에서 검증 수행
  - Patch 검증은 현재 revision이 Worktree에 적용되고 M06 Post-Apply Diff Guardrail을 통과한 뒤 Final Risk / Verification Plan이 확정된 경우에만 수행

- `kh apply`
  - `VERIFIED` Patch에 대한 사용자 최종 승인 동작
  - 승인 후 `APPROVED`로 상태 전환
  - Source Consistency Check 통과 시에만 원본 반영
  - 이미 `APPROVED` 되었지만 실제 Apply가 완료되지 않은 동일 revision은 Apply Recovery 경로로 재개 가능

- `kh history`
  - 분석 / Patch / Verification 이력 조회

---

## M01-FR-02. CLI-first

코드 수정과 검증의 Primary Work Surface는 CLI다.

Web은 원본 코드를 직접 수정하는 기본 인터페이스가 아니다.
CLI도 Repository path / symbol / test output / Audit reason 등 untrusted 문자열을 terminal control sequence나 escape instruction으로 직접 해석하지 않고 display-safe escaping / structured rendering을 적용한다.

---

## M01-FR-03. Repository 자동 인식

현재 cwd에서 Git root를 탐색한다.

필수 확인:

```text
repository_root
canonical_repository_root
repository_id
branch
commit_sha
working_tree_dirty
working_tree_diff_hash
head_state
git_operation_state
```

Repository 밖에서 실행한 경우 명시적 경로 입력을 요구할 수 있다.

Repository ACL / RBAC 조회 전에 사용자 입력 경로를 신뢰하지 않고 Repository Identity를 canonicalize한다.

필수 원칙:

- symlink / junction / 상대경로 / path alias를 정규화한 physical `canonical_repository_root`를 확정한다.
- ACL 판단은 사용자 입력 path string이 아니라 등록된 stable `repository_id`와 canonical root mapping을 기준으로 수행한다.
- Git linked worktree를 지원하는 경우 shared repository identity와 현재 worktree root를 구분해 기록한다.
- Repository discovery / identity 확인 과정에서 repository-controlled hook / filter / external command를 실행하지 않는다.
- Git object database가 external alternates / shared object store / partial-clone promisor에 의존하는 경우 해당 object source를 Repository identity / ACL / Local-Only boundary 안에서 검증한다. Unauthorized external object store를 parent Repository 권한으로 자동 신뢰하지 않는다.
- Repository discovery / status / introspection은 missing object를 채우기 위한 implicit network fetch를 수행하지 않으며, object가 로컬에 없으면 명시적 policy 경로 없이 자동 다운로드하지 않는다.
- 동일 Repository가 다른 path alias로 접근되더라도 ACL을 우회해 별도 Repository로 취급하지 않는다.
- `head_state`와 merge / rebase / cherry-pick / revert / sequencer 등 in-progress Git operation state를 non-executing Safe Git introspection으로 확인한다.
- 1차 구현에서 `MODIFY / OPTIMIZE / APPLY`는 resolvable base commit과 명확한 target branch가 존재하고 destructive/in-progress Git operation이 없는 `NORMAL` mutation state에서만 시작한다. Detached HEAD / unborn repository / merge·rebase·cherry-pick 등 진행 중 상태는 명시적 지원 설계가 없는 한 mutation 계열을 fail-closed로 차단한다. READ-ONLY 분석은 해당 상태를 결과에 명시한 뒤 허용할 수 있다.

---

## M01-FR-04. Identity Establishment

Repository ACL 적용 전에 CLI 사용자를 식별하고 canonical Repository Identity를 확정한다.

```text
CLI Invocation
→ Identity Establishment
→ Canonical Repository Identity
→ Repository ACL / RBAC
→ Source / Graph / LLM Access
```

1차 구현 Identity Source 후보:

```text
A. Knowledge Hub 로그인 / JWT
B. Local OS User ↔ Knowledge Hub User Mapping
```

필수 규칙:

- 내부 `user_id` 확정 전 보호된 Repository 분석 금지
- 인증 토큰 원문 로그 저장 금지
- Web과 CLI는 동일 Repository 권한 정책 사용
- Web 인증 연동 시 안전한 local credential storage 사용

---

## M01-FR-05. Repository ACL / RBAC

권한 검사는 Retrieval / Analysis / LLM context 생성보다 먼저 수행한다.

```text
Unauthorized Repository
→ Source 조회 차단
→ Graph 조회 차단
→ Retrieval 차단
→ LLM Context 포함 차단
```

생성 후 마스킹 방식으로 대체하지 않는다.
Canonical Repository Identity 확인에 필요한 최소 filesystem / Git metadata 외의 branch detail / history / source-derived metadata도 보호 대상 Repository에서는 ACL 통과 후 조회하는 것을 기본으로 한다.

---

## M01-FR-06. `kh verify` / `kh apply` 차단 규칙

Patch 기반 `kh verify`는 다음 선행조건을 만족해야 한다.

```text
APPLIED_TO_WORKTREE
+ Canonical Actual Change Set = COMPLETE
+ Post-Apply Diff Guardrail = ALLOW
+ Final Change Risk available
+ Verification Plan available
```

Pre-Apply / Post-Apply Guardrail에 의해 차단된 revision, `PATCH_APPLY_FAILED`, 또는 Worktree에 적용되지 않은 revision은 `kh verify`로 검증 파이프라인을 우회할 수 없다.


다음 상태에서는 `kh apply`를 허용하지 않는다.

```text
PATCH_APPLY_FAILED
FAILED
INCONCLUSIVE
STALE_VERIFICATION
```

`VERIFIED` 상태에서 current Identity / Repository Approval·Apply 권한을 확인하고 사용자가 `kh apply`를 확인한 뒤, Approval binding과 `APPROVED` state transition이 M09의 crash-consistent durable store에 성공적으로 기록된 경우에만 `APPROVED`로 전환한다. Approval persistence가 실패하면 `CRITICAL_PERSISTENCE_FAILED`로 처리하고 `VERIFIED`를 유지하며 Repository side effect를 시작하지 않는다.
단, 해당 revision의 canonical verified Patch artifact가 durable Local Store에 존재하고 저장된 hash / revision 무결성 검사를 통과해야 승인 대상으로 이동할 수 있다.
Approval 직전 current Verification / Guardrail / Risk policy basis가 저장된 `verification_basis_id`와 동일하거나 명시적으로 backward-compatible한지 확인하며, 불일치하면 기존 Verification을 승인에 사용하지 않고 re-validation을 요구한다. 이 경우 Patch content가 바뀐 것은 아니므로 새 revision을 자동 생성하지 않는다.
Backward-compatibility 판정은 LLM 단독 판단이 아니라 M07/M09에 기록되는 versioned trusted policy / deterministic compatibility rule 또는 authorized administrative decision에 근거해야 한다.
사용자 승인 이벤트는 승인 대상 `patch_id / revision / patch_hash / final_diff_hash / verification_result_id / verification_basis_id / request_intent_id / approval_evidence_hash-or-reference`와 `approver_user_id / approval_policy_version` 또는 동등한 승인 권한 기준점을 명시적으로 바인딩해야 하며, 해당 식별자나 승인 정책 기준이 변경되면 기존 승인을 무조건 capability처럼 재사용하지 않는다.

사용자 최종 승인은 informed approval이어야 한다. `kh apply` 확인 직전 최소 다음 Evidence를 structured summary로 표시한다.

```text
Patch identity / revision / hash
Canonical Actual Change Set summary
Original request intent / protected request reference + acceptance criteria mapping summary
Final Change Risk / 주요 Risk factor
Required Verification Check 결과
INCONCLUSIVE / NOT_AVAILABLE 여부
Sensitive / Security exception 또는 declassification / remote-publish 관련 여부
Verification Basis / policy version reference
```

승인 UI/CLI는 LLM의 자연어 설명만을 approval authority로 사용하지 않으며, 위 Evidence의 exact binding을 사용자가 식별 가능한 형태로 제공해야 한다. 사용자는 승인 전에 exact canonical Patch artifact / Canonical Actual Change Set의 상세 내용을 current ACL / sensitive policy 범위에서 inspection할 수 있어야 하며, summary만 제공하고 underlying change를 검토할 수 없는 상태를 강제하지 않는다. 사용자가 실제 확인한 structured approval Evidence snapshot에는 immutable hash/reference를 부여해 Approval binding과 함께 Audit한다. 표시 Evidence는 동일 `verification_result_id / verification_basis_id / request_intent_id`에서 resolve된 authoritative structured data여야 하며 stale cache / 다른 revision의 summary를 혼합하지 않는다. Sensitive content 표시는 M08 ACL / redaction / provenance policy를 따른다.

`kh apply` 및 Apply Recovery 실행 시점에는 현재 Identity와 Repository `APPLY` 권한을 다시 확인한다.
기존 Approval은 현재 ACL / RBAC를 우회하는 영구 capability로 취급하지 않는다.
승인 이후 권한이 철회되었거나 현재 적용 정책상 기존 Approval binding의 승인 자격이 유효하지 않으면 Apply를 차단하고 Audit에 기록한다. Verification 자체가 여전히 유효한 경우 기존 Approval을 무효화하고 `VERIFIED`로 되돌려 새 승인 절차를 요구할 수 있으며, Verification Basis까지 stale이면 `STALE_VERIFICATION`으로 처리한다.

이미 `APPROVED` 상태인 동일 `patch_id / revision`에서 실제 Repository Apply가 완료되지 않은 경우에는 새 승인 이벤트를 생성하지 않고 Apply Recovery를 허용할 수 있다.

Apply Recovery 필수 규칙:

- 기존 승인 대상 `patch_id / revision / patch_hash / final_diff_hash / verification_result_id / verification_basis_id / approval_binding_id`가 동일해야 한다.
- Recovery 실행 사용자의 현재 Identity / Repository `APPLY` 권한과 기존 Approval binding의 현재 유효성을 다시 확인한다.
- Repository write lock / serialization을 다시 획득한다.
- Repository identity / branch와 durable Apply Attempt의 `pre_apply_source_hash / expected_post_apply_result_hash`를 기준으로 현재 Repository state를 reconcile한다.
- `PRE_APPLY_MATCH`이면 동일 verified artifact의 Apply를 재시도할 수 있고, `EXPECTED_POST_APPLY_MATCH`이면 중복 Apply 없이 이전 Apply 성공으로 reconcile하여 M05의 Post-Apply Integrity 규칙에 따라 `APPLIED`로 전환할 수 있다.
- pre/post 어느 기준에도 일치하지 않는 변경 / partial / unknown state만 `STALE_VERIFICATION` 또는 remediation required로 처리한다.
- 일시적인 lock 획득 실패는 기존 Verification / Approval을 무효화하지 않으며 Patch 상태는 `APPROVED`를 유지한다.

---

# 3. 입력

```text
CLI command
CLI args
cwd / repo path
user identity credential
target symbol / natural-language request
```

---

# 4. 출력

```text
CommandRequest
user_id
repository_id / repository_path / canonical_repository_root
target
task
interactive approval result
approval_evidence_reference
```

---

# 5. 의존 모듈

- M02 Repository Context
- M03 Query Planner
- M05 Patch Lifecycle
- M08 Local-Only Security
- M09 Audit

---

# 6. 오류 / 차단 조건

```text
IDENTITY_UNRESOLVED
ACCESS_DENIED
APPLY_AUTHORIZATION_DENIED
APPROVAL_AUTHORIZATION_REVOKED
NOT_A_GIT_REPOSITORY
REPOSITORY_STATE_BLOCKED
DIRTY_WORKTREE_BLOCKED
PATCH_NOT_READY_FOR_VERIFICATION
PATCH_NOT_VERIFIED
VERIFIED_ARTIFACT_UNAVAILABLE
VERIFICATION_BASIS_MISMATCH
WORKTREE_PREPARATION_BLOCKED
CANONICAL_CHANGE_SET_UNAVAILABLE
PROPOSAL_BASE_STALE
CRITICAL_PERSISTENCE_FAILED
APPLY_LOCK_UNAVAILABLE
STALE_VERIFICATION
```

---

# 7. 성공 기준

- CLI가 repo / branch / commit / HEAD / in-progress Git operation state를 자동 인식할 수 있다.
- path alias / symlink 등에 영향받지 않는 canonical Repository Identity를 확정할 수 있다.
- Identity 확인 및 canonical Repository Identity 확정 후 ACL을 적용할 수 있다.
- 권한 없는 코드가 LLM context에 들어가지 않는다.
- Guardrail / Worktree / Final Risk 선행조건을 충족하지 않은 Patch는 Verification을 시작할 수 없다.
- `VERIFIED`가 아니거나 canonical verified Patch artifact를 안전하게 복원할 수 없는 Patch는 승인 / 원본 반영할 수 없다.
- 사용자의 `kh apply` 확인 전에 exact request intent / acceptance mapping / Change Set / Risk / Verification / exception Evidence를 structured informed-approval summary로 제공하고, 해당 summary가 승인 binding과 동일 basis에서 resolve되었음을 확인할 수 있다.
- 사용자의 `kh apply` 확인이 정확한 Patch revision / hash / Verification Result / Verification Basis에 바인딩된 명시적 승인 이벤트로 기록된다.
- Apply / Recovery 시 현재 Identity와 Repository 권한을 재검증하여 과거 Approval만으로 권한 철회를 우회하지 않는다.
- `APPROVED` 이후 프로세스가 중단되어도 동일 revision의 Apply를 새 승인 없이 안전하게 재개할 수 있다.
- 일시적인 Apply lock 획득 실패만으로 Verification / Approval을 무효화하지 않는다.

---

# M02. Repository Context / Code Graph

## 1. 책임

현재 Repository의 실제 상태를 정확하게 정의하고,
파일·함수·의존성 관계를 분석 가능한 Evidence로 제공한다.

Potpie Code Graph는 보조 Evidence이며 현재 Source보다 높은 권위를 갖지 않는다.

---

# 2. 핵심 요구사항

## M02-FR-01. Repository 등록

다음 정보를 확인한다.

```text
local path
canonical repository root
repository_id
Git repository 여부
current branch
current commit SHA
HEAD state (normal / detached / unborn 등)
Git operation state (merge / rebase / cherry-pick / revert / sequencer 등)
Git object/materialization state (alternates / partial clone / sparse checkout 등)
분석 언어
민감 파일 제외 정책
```

민감 파일 예:

```text
.env
.env.*
*.pem
*.key
*.p12
*.pfx
credentials.json
secret/
secrets/
```

---

## M02-FR-02. Dirty Working Tree

필수 상태:

```text
base_commit
working_tree_dirty
working_tree_diff_hash
working_tree_source_snapshot_hash
staged_diff_hash
unstaged_diff_hash
```

1차 구현 정책:

```text
READ-ONLY STATIC ANALYSIS (EXPLAIN / IMPACT)
→ dirty 허용
→ 현재 source + working tree diff를 분석

RUNTIME ANALYSIS (PROFILE / PERFORMANCE)
→ dirty이면 기본 차단
→ commit / stash / clean 요구
→ 단, dirty snapshot을 Temporary Worktree / Sandbox에 정확히 재현하는 기능이 구현된 경우에만 허용 가능

MODIFY / OPTIMIZE / APPLY
→ dirty이면 기본 차단
→ commit / stash / clean 요구
```

Dirty 상태를 무시하고 Patch 생성 / Verification / Runtime Profiling을 진행하지 않는다.

Dirty snapshot 재현은 확장 범위다.

`working_tree_dirty` / source snapshot 계산은 tracked staged / unstaged 변경뿐 아니라 분석 대상에 포함되는 relevant untracked source도 누락하지 않아야 한다.
단순 `git diff` hash만으로 현재 Source 전체 상태를 대표하지 않는다.
`working_tree_source_snapshot_hash`는 Sensitive File / ingestion policy를 적용한 현재 분석 대상 source set의 실제 content state를 식별할 수 있어야 한다.

Repository / Graph ingestion 경계:

- source traversal은 `canonical_repository_root`를 기준으로 한다.
- parent Repository 내부에서 별도 `.git` directory/file, linked worktree metadata 또는 submodule working tree 등 독립 Git boundary가 발견되면 nested Repository 후보로 분류한다.
- parent Repository ACL만으로 nested Repository의 source / history / Graph / modification 권한을 자동 상속하지 않는다. nested Repository는 별도의 canonical `repository_id`와 ACL 확인 없이 traversal / ingestion / modification하지 않는 것을 기본으로 한다.
- Git submodule의 gitlink metadata는 parent Repository Evidence로 볼 수 있지만 submodule working tree content는 등록 / ACL이 확인된 별도 Repository context로 취급한다.
- symlink / junction을 따라 canonical Repository root 밖의 파일을 ingestion / Retrieval / Graph source로 읽지 않는다.
- bind mount / mount-point / platform reparse-point 등 path 문자열이나 realpath만으로 충분히 드러나지 않는 filesystem boundary를 고려한다. 별도 trusted root / Repository identity로 연결된 mount boundary를 parent Repository source로 자동 traversal하지 않으며, 안전한 범위를 확인할 수 없으면 fail-closed로 제외한다.
- `.git` 및 worktree administrative metadata는 Source / Graph ingestion 대상에서 제외한다.
- Git object alternates / shared object store / replace-ref / partial-clone source가 현재 Repository 밖 content를 공급하는 경우 ACL / trusted object-store mapping을 검증하고, authorization을 확인할 수 없는 object source를 Graph / Retrieval에 사용하지 않는다.
- missing Git object를 채우기 위한 implicit network fetch는 Repository analysis 중 기본 금지한다. 필요한 object가 local/authorized store에 없으면 Graph / source completeness를 `PARTIAL` 또는 blocked로 표현하고 M08 allowlist 없는 fetch를 시도하지 않는다.
- sparse checkout / skip-worktree 등 materialization scope가 전체 tracked source보다 좁은 경우 해당 scope를 SourceSnapshotReference에 기록하고, 전체 source를 분석했다고 주장하지 않는다.
- symlink 자체를 분석 대상으로 표현할 수는 있지만, target content를 읽을 때는 resolved target path와 M08 Sensitive File Policy를 다시 적용한다.

---

## M02-FR-03. Branch / Commit-aware Analysis

모든 분석 결과에 다음 기준점을 연결한다.

```text
branch
commit_sha
working_tree_dirty
working_tree_diff_hash
working_tree_source_snapshot_hash
```

Code Graph freshness는 commit SHA만으로 판정하지 않는다.

Graph 생성 / 갱신 시 최소 다음 기준점을 연결한다.

```text
graph_base_commit
graph_source_snapshot_hash
graph_working_tree_diff_hash
graph_snapshot_schema_version
```

현재 commit이 동일하더라도 `working_tree_diff_hash` 또는 source snapshot이 Graph 생성 기준과 다르면 현재 Source를 완전히 반영한 Graph로 간주하지 않는다.
이 경우 `GraphFreshness`를 `STALE` 또는 `PARTIAL`로 표시하고, 현재 Source 기준 재검증 / 증분 갱신 전까지 `FRESH`로 표시하지 않는다.
Clean working tree에서는 `graph_working_tree_diff_hash`를 clean sentinel 또는 동등한 방식으로 명시적으로 표현할 수 있다.
`graph_source_snapshot_hash`의 범위는 Sensitive File 제외 정책 등 Graph ingestion policy를 적용한 실제 graph-covered source set과 일치해야 하며, snapshot scope / policy가 달라진 경우 동일 hash 의미로 재사용하지 않는다.
Snapshot / hash 의미는 `graph_snapshot_schema_version` 또는 동등한 canonicalization version과 함께 기록하여 버전이 다른 hash를 동일 semantics로 비교하지 않는다.

---

## M02-FR-04. Incremental Update

```text
Repository Source Change
→ Changed Files Detection (tracked + relevant untracked source)
→ Changed Symbols Detection
→ Code Graph Incremental Update
→ Current Commit / Source Snapshot Mapping
```

Changed Files Detection은 단순 `git diff`에 한정하지 않고 현재 Graph ingestion policy 범위의 relevant untracked source와 source snapshot 변화를 포함한다.
전체 Repository 재분석만을 유일한 방법으로 강제하지 않는다.

---

## M02-FR-05. 파일 관계 분석

제공 정보:

- 파일 역할
- import 대상
- dependency
- 해당 파일을 호출하는 파일
- 관련 configuration
- 관련 test

---

## M02-FR-06. 함수 / 메서드 관계 분석

제공 정보:

```text
calls
called_by
input
output
exception
side effect
shared dependency
external boundary
```

---

## M02-FR-07. Potpie Local-Only

Potpie는 Self-hosted / Local deployment only다.

```text
Potpie Runtime        LOCAL
Code Graph Storage    LOCAL
Embedding             LOCAL
LLM Provider          LOCAL
Telemetry             DISABLED
Source Transmission   EXTERNAL DISABLED
```

금지:

- Potpie Cloud로 source 전송
- 외부 LLM
- 외부 embedding
- 외부 telemetry를 통한 코드 / 분석 메타데이터 전송

외부 provider 설정을 탐지하면 Code Intelligence 실행을 차단한다.
Potpie / Graph Adapter / parser는 Repository source를 Evidence로 처리하되 Repository code / build hook / plugin을 임의 실행하지 않는 non-executing ingestion profile을 기본으로 한다. 특정 extractor가 project execution을 요구하면 M06 Command Policy / Sandbox 경계를 사용하며 Graph ingestion이라는 이유로 Host execution 권한을 얻지 않는다.

---

# 3. Evidence Priority

Evidence 우선순위는 사실의 종류에 따라 구분한다.

### Structural / Code Fact

```text
Current Source Code
>
Static Analysis / LSP
>
Current Potpie Code Graph
>
LLM Recommendation
```

### Runtime / Performance Fact

```text
Runtime / Test / Benchmark / Profiler
>
Current Source Code
>
Static Analysis / LSP
>
Current Potpie Code Graph
>
LLM Recommendation
```

Graph가 stale이거나 불완전하면 현재 Source로 재검증한다.
Runtime / Performance 사실은 실제 측정 Evidence가 존재하는 경우 이를 우선한다.

---

# 4. 출력 데이터

```text
RepositoryContext
SourceSnapshotReference
FileGraph
FunctionGraph
DependencyGraph
ChangedFiles
ChangedSymbols
GraphFreshness
GraphSourceSnapshotReference
HeadState
GitOperationState
GitObjectMaterializationState
NestedRepositoryBoundaries
FilesystemBoundaryEvidence
```

---

# 5. 의존 모듈

- M01 Identity / ACL
- M08 Local-Only Security
- M09 Analysis Store

---

# 6. 성공 기준

- 파일 관계를 시각화 가능한 형태로 제공한다.
- 함수 호출관계를 제공한다.
- graph 결과를 현재 branch / commit / source snapshot에 연결한다.
- dirty working tree의 diff / source snapshot이 Graph 기준 snapshot과 다르면 stale / partial graph를 탐지한다.
- relevant untracked source와 symlink / mount / nested-repository traversal boundary를 포함해 현재 분석 대상 source snapshot을 식별할 수 있다.
- nested Repository / submodule working tree boundary를 별도 Repository identity 후보로 표현하고 parent ACL만으로 자동 traversal하지 않는다.
- Repository root 밖 symlink target / untrusted mount boundary / `.git` metadata가 Graph / Retrieval source로 유입되지 않는다.
- dirty working tree에서 Runtime Profiling을 수행할 때 snapshot 재현 가능 여부를 확인하고, 재현 불가 시 실행을 차단한다.
- detached / unborn / in-progress Git operation 상태를 Repository Context에 표현하고 mutation 계열의 fail-closed 판단에 제공할 수 있다.
- Potpie가 완전 로컬 상태인지 검증할 수 있다.

---

# M03. Query Planner / Code Understanding

## 1. 책임

사용자 자연어 질의를 구조화하고,
코드 설명 / 영향 분석 / 수정 / 성능 분석 등 적절한 실행 경로로 라우팅한다.

---

# 2. Planner 모델

## M03-FR-01. Domain

```text
KNOWLEDGE
CODE
```

---

## M03-FR-02. Task

```text
EXPLAIN
IMPACT
MODIFY
PERFORMANCE
OPTIMIZE
VALIDATE
```

---

## M03-FR-03. Reasoning Intent

```text
FACT_LOOKUP
COMPARISON
CAUSE_ANALYSIS
TROUBLESHOOTING
DESIGN_PROPOSAL
NOVELTY_ASSESSMENT
VALIDATION_PLAN
```

한 질문이 Task와 Reasoning Intent를 동시에 갖는다.

예:

```text
"왜 이 함수가 느려?"

domain = CODE
task = PERFORMANCE
reasoning_intent = CAUSE_ANALYSIS
```

---

# 3. Planner 출력

최소 다음 정보를 표현할 수 있어야 한다.

```json
{
  "domain": "CODE",
  "task": "OPTIMIZE",
  "reasoning_intent": "CAUSE_ANALYSIS",
  "resolved_query": "...",
  "target_entities": ["build_candidates"],
  "needs_retrieval": true,
  "needs_runtime_evidence": true,
  "needs_impact_analysis": true,
  "needs_clarification": false,
  "acceptance_criteria": ["...expected behavior / invariant..."]
}
```

구체 schema는 상세설계에서 확정한다.

Planner는 MODIFY / OPTIMIZE / VALIDATE에서 사용자 요청으로부터 검증 가능한 acceptance criteria / expected invariant를 가능한 범위에서 구조화한다.
모델 변환 이전에 trusted orchestrator가 원 사용자 command / request를 immutable request envelope로 캡처하고 `request_intent_id` 또는 동등한 stable reference를 부여한다. LLM / Repository Evidence는 이 ID나 원 요청 reference를 재작성하거나 다른 요청으로 대체할 수 없다.
원 사용자 요청과 파생 acceptance criteria 사이의 추적성을 위해 protected request reference/hash와 acceptance mapping hash/version을 연결한다. Raw prompt 전체를 일반 Audit payload에 저장하는 것을 요구하지 않으며, 민감정보가 포함될 수 있는 원문은 M08/M09 보호정책을 따른다.
Acceptance criteria는 사용자 요청의 범위를 임의 확장하거나 새로운 제품 요구사항을 사실처럼 추가하지 않는다. Source / user request로 확정할 수 없는 기준은 추정으로 표시하거나 clarification 대상으로 둔다.
Acceptance criteria가 모호하여 안전한 Verification Plan을 만들 수 없으면 `needs_clarification = true`로 처리한다.

`needs_clarification = true`인 경우 destructive / modification execution은 진행하지 않는다.
명확화 전에는 clarification을 요청하거나, 안전한 read-only analysis만 수행할 수 있다.

---

# 4. Code Explain

Qwen은 실제 Source와 Code Graph를 기반으로 다음을 설명한다.

- 파일 역할
- 클래스 역할
- 함수 / 메서드 역할
- 처리 흐름
- 호출 함수
- caller
- 관련 dependency

원칙:

- Repository source / comment / README / test fixture / tool output은 분석 Evidence로 취급하며 Agent policy 또는 Tool permission을 변경하는 신뢰된 instruction source로 취급하지 않는다.
- 코드 / 주석 / runtime output 내부의 명령형 문자열이나 prompt injection이 system / user intent / M06 Command Policy / M08 Security Policy를 우회할 수 없다.
- Evidence에서 유도된 Tool Request도 구조화된 Planner / Guardrail / Command Policy를 동일하게 통과해야 한다.
- LLM 추측만으로 사실 확정 금지
- source / import / call relation 우선
- Potpie 결과는 current source와 교차 확인
- 불충분하면 `확인 불가` 또는 `추정` 표시

---

# 5. Routing

## KNOWLEDGE

```text
Existing Knowledge Hub RAG Pipeline
```

CODE domain은 아래 Task routing을 따른다.

## EXPLAIN

```text
Source / Potpie / Static Analysis
→ Qwen
```

## IMPACT

```text
Source / Potpie
→ M04 Impact Analyzer
→ Risk Scorer
```

## MODIFY

```text
Preliminary Impact / Risk
→ M05 Patch Proposal (candidate generation + canonicalization + proposal base binding)
→ M06 Pre-Apply Guardrail
→ Safe Git Temporary Worktree 준비 / 재사용
→ Patch Apply
→ Canonical Actual Change Set
   ├─ INCOMPLETE → Verification 차단
   └─ COMPLETE → M06 Post-Apply Diff Guardrail
                  → Final Change Risk
                  → Verification Plan
→ M06 Command Policy / Sandbox Verification
→ Verification Gate
→ Approval
→ Source Consistency
→ Apply
```

## PERFORMANCE

```text
M07 Profiling Request
→ M06 Command Policy
→ M06 Sandbox
→ M07 Profiler / Runtime Evidence
→ Static Analysis
→ Qwen
```

## OPTIMIZE

```text
Preliminary Impact / Risk
→ Safe Git Temporary Worktree
→ M06 Command Policy / Sandbox Baseline
→ M07 Profiler / Benchmark / Static
→ M05/M06 Baseline Worktree Source Integrity Check
→ New Pre-Patch Evidence
→ Preliminary Impact / Risk Refresh if needed
→ Qwen candidate change
→ M05 Patch Proposal canonicalization + proposal base binding
→ M06 Pre-Apply Guardrail
→ Safe Git Temporary Worktree 확인
→ Apply Patch to Temporary Worktree
→ Canonical Actual Change Set
   ├─ INCOMPLETE → Verification 차단
   └─ COMPLETE → M06 Post-Apply Diff Guardrail
                  → Final Risk
                  → Verification Plan
→ M06 Command Policy / Sandbox Test / Benchmark
→ Verification Gate
→ Approval
→ Source Consistency
→ Apply
```

## VALIDATE

```text
Current Patch / Target
→ Verification Requirement Resolve
→ M07 Verification Plan
→ M06 Command Policy / Sandbox
→ M07 Verification Gate
```

---

# 6. 의존 모듈

- M02 Source / Graph
- M04 Impact / Risk
- M05 Patch Lifecycle
- M06 Command Policy / Sandbox
- M07 Verification / Profiling

---

# 7. 성공 기준

- 코드 질의와 기존 Knowledge 질의를 분리할 수 있다.
- KNOWLEDGE 질의는 기존 Knowledge Hub RAG 경로로 전달할 수 있다.
- Task와 Reasoning Intent를 독립적으로 표현한다.
- MODIFY / OPTIMIZE / VALIDATE 요청의 acceptance criteria / expected invariant를 Verification Plan으로 전달할 수 있다.
- 원 사용자 요청의 `request_intent_id` / protected request reference와 acceptance mapping을 Verification Basis까지 추적 가능하게 연결할 수 있다.
- Explain 결과가 Source Evidence에 근거한다.
- VALIDATE가 M06 / M07 검증 경로로 연결된다.
- `needs_clarification = true`인 상태에서 destructive / modification execution을 진행하지 않는다.
- PERFORMANCE / OPTIMIZE의 runtime 실행은 M06 Command Policy / Sandbox 경로를 우회하지 않는다.
- OPTIMIZE baseline 실행 부산물이 Worktree source 또는 이후 Canonical Actual Change Set를 오염시키지 않았는지 확인한 뒤 Patch 생성 / 적용 단계로 진행한다.
- 새로운 pre-patch runtime/static evidence가 확보되면 Preliminary Risk를 최신 Evidence 기준으로 갱신할 수 있다.
- MODIFY / OPTIMIZE의 Patch는 Worktree 적용 전에 M06 Pre-Apply Guardrail을 통과한다.
- MODIFY / OPTIMIZE가 검증 파이프라인을 우회하지 않는다.

---

# M04. Change Impact / Risk Analysis

## 1. 책임

변경 전 예상 영향범위와 실제 Patch 적용 후 영향범위를 분석하고,
Rule-based Risk Score를 산출한다.

LLM은 Risk Score 숫자를 직접 결정하지 않는다.

---

# 2. Change Impact / Blast Radius

분석 대상:

- direct caller
- indirect caller
- related tests
- test / benchmark harness 및 verification config
- config
- persistence
- external dependency
- API contract
- shared symbol
- runtime boundary

---

# 3. Preliminary Risk

Patch 생성 전에 계산한다.

근거:

```text
User Request
+
Target Symbol
+
Current Call Graph
+
External Boundary
+
Current Test Coverage
```

용도:

- 변경 계획
- Patch 생성 전략
- 예상 검증 범위

Preliminary Risk는 Verification Authority가 아니다.

Patch 생성 전 Profiler / Static Analysis 등 새로운 Evidence가 추가되면 Preliminary Risk를 최신 Evidence 기준으로 재계산할 수 있다.
재계산된 최신 Preliminary Risk는 이후 변경 계획과 Patch 생성 전략에 사용하되, 이전 계산 이력은 Audit에서 추적 가능해야 한다.
Preliminary Risk의 재계산은 Canonical Actual Change Set 기반 Final Change Risk를 대체하지 않는다.

---

# 4. Final Change Risk

Patch를 Temporary Worktree에 적용한 뒤
M05가 생성한 `Canonical Actual Change Set`을 기준으로 다시 계산한다.
단순 `git diff` 출력만을 전체 변경의 authority로 사용하지 않는다.

근거:

```text
Canonical Actual Change Set
+
Changed Files
+
Changed Symbols
+
Updated Blast Radius
+
Config / API / Persistence Change
+
Security Impact
+
File type / mode / symlink / submodule change
```

Final Change Risk가 최종 Verification Plan을 결정한다.
M06 / M08에서 허용된 sensitive-file / security policy exception도 `Security Impact` Evidence로 유지하며, Guardrail에서 허용되었다는 이유만으로 Risk factor에서 제거하지 않는다.

---

# 5. Risk Score

후보 요소:

- caller 수
- dependency 수
- cyclomatic complexity
- test coverage
- test deletion / modification / skip-config 영향
- 최근 변경 빈도
- runtime hotspot
- external boundary
- shared symbol
- persistence 영향
- security 영향
- symlink / executable mode / gitlink / special file type 영향

기본 threshold:

```text
0  - 39   LOW
40 - 69   MEDIUM
70 - 100  HIGH
```

Threshold는 설정 가능해야 하고,
결과에 사용한 threshold version과 Risk rule / scoring algorithm version을 기록한다.
가중치 / factor normalization / missing-evidence 처리 규칙 등 Risk 계산 semantics가 바뀌면 `risk_rule_version` 또는 동등한 버전을 변경해야 하며, threshold가 동일하다는 이유만으로 이전 Risk semantics와 동일하다고 간주하지 않는다.

Risk factor evidence가 `unavailable`인 경우 해당 요소를 임의로 0점 처리하지 않는다.
Missing evidence는 `RiskFactors`에 명시적으로 기록하고,
필요한 Evidence가 부족하면 Verification Plan을 보수적으로 확대할 수 있어야 한다.

---

# 6. Rule-based Score → LLM Explanation

```text
Rule-based Score
→ Risk Level
→ Qwen Explanation
```

Qwen은 Risk 원인을 설명할 수 있지만 점수를 임의 생성하지 않는다.

---

# 7. Patch revision과 Risk

Patch 내용이 변경되면:

```text
old final risk → invalid
new Canonical Actual Change Set → recompute final risk
new verification plan
```

기존 Final Risk를 새 revision에 재사용하지 않는다.

---

# 8. 출력

```text
ImpactResult
PreliminaryRisk
FinalChangeRisk
RiskLevel
RiskFactors
MissingRiskEvidence
ThresholdVersion
RiskRuleVersion
ChangedSymbols
AffectedTests
```

---

# 9. 의존 모듈

- M02 Repository / Graph
- M05 Canonical Actual Change Set
- M07 Verification Planner

---

# 10. 성공 기준

- 변경 영향 범위를 식별한다.
- Preliminary Risk와 Final Risk를 구분한다.
- Canonical Actual Change Set / `final_diff_hash`가 바뀌면 Final Risk를 다시 계산한다.
- Risk evidence가 부족한 요소를 임의의 안전한 값으로 축소하지 않는다.
- Missing Risk Evidence를 결과에 기록할 수 있다.
- Patch 생성 전 새로운 Evidence가 확보되면 Preliminary Risk를 재계산할 수 있다.
- 허용된 security policy exception도 Final Risk Evidence로 반영할 수 있다.
- Risk Level이 Verification Plan과 연결된다.
- Risk 계산 semantics / threshold가 어떤 version에서 산출되었는지 식별할 수 있다.

---

# M05. Patch Lifecycle / Worktree / Source Consistency

## 1. 책임

M03가 확정한 modification intent를 바탕으로 생성된 candidate Patch를 canonical Patch Proposal로 수용 / 식별하고,
원본 Repository를 보호하면서 Temporary Worktree에서 변경을 적용하며,
Patch revision / lifecycle / 최종 적용 무결성을 관리한다.

---

# 2. Patch 기본 정책

```text
원본 자동 수정            금지
Patch 제안                허용
Temporary Worktree 적용   자동 가능
원본 Repository 반영      사용자 최종 승인 필수
```

Patch 생성만으로 원본을 변경하지 않는다.

Patch Proposal 경계:

- M03는 사용자 intent / target / acceptance criteria를 구조화하고 routing하며, candidate code/diff 생성은 Local LLM/Qwen 또는 등록된 generator가 수행할 수 있다.
- M05는 candidate output을 raw shell/instruction으로 실행하지 않고 canonical Patch Proposal artifact로 변환 / 검증한다.
- canonical Proposal에는 최소 `request_intent_id / proposal_base_repository_id / proposal_base_branch / proposal_base_commit / proposal_source_snapshot_hash / preliminary_risk_reference / target paths / intended operation manifest / patch content-or-reference / patch_artifact_schema_version / generator provenance`를 연결하고 `patch_id / patch_revision / patch_hash`를 부여한 뒤 `PROPOSED` lifecycle에 진입한다.
- `request_intent_id / proposal base / preliminary_risk_reference / policy context` 같은 authority-bearing binding은 candidate/LLM output에서 신뢰해 채우지 않고 trusted orchestrator / M01~M04 state에서 주입한다. Candidate가 해당 값을 포함하더라도 authoritative state를 덮어쓸 수 없다.
- `patch_hash`는 patch content뿐 아니라 `request_intent_id / proposal base binding / intended operation manifest`를 포함하는 canonical Patch Proposal identity와 `patch_artifact_schema_version / hash_algorithm` 또는 동등한 canonicalization version에 연결하여, 동일 diff text라도 다른 요청·base·target semantics를 같은 Patch로 오인하지 않는다.
- Pre-Apply Guardrail / Worktree Apply 전에 현재 target Repository / branch / source snapshot이 Proposal base binding과 일치하는지 확인한다. target branch head 또는 source snapshot이 바뀌었으면 옛 Preliminary Risk / Proposal을 새 source에 조용히 재사용하지 않고 `PROPOSAL_BASE_STALE` Audit / proposal regeneration 또는 re-analysis를 요구한다. Patch content가 아직 변경되지 않았다는 이유만으로 stale base를 허용하지 않는다.
- canonicalize할 수 없는 candidate output, ambiguous target, unsupported filesystem operation은 `PROPOSED`로 승격하지 않고 generation / proposal error로 처리한다.
- candidate 생성과 canonical Proposal 생성만으로 원본 Repository 또는 Worktree source를 수정하지 않는다. 실제 mutation은 M06 Pre-Apply Guardrail 이후 M05의 controlled apply 경로에서만 발생한다.

---

# 3. Patch Lifecycle

```text
PROPOSED
→ M06 Pre-Apply Guardrail
   ├─ deny  → Worktree Apply 금지 / Audit 기록 / PROPOSED 유지
   └─ allow → Ensure Safe Git Temporary Worktree
               ├─ blocked / unsafe → WORKTREE_PREPARATION_BLOCKED Audit / PROPOSED 유지
               └─ ready → Apply Patch to Temporary Worktree
                           ├─ success → APPLIED_TO_WORKTREE
                           └─ fail    → PATCH_APPLY_FAILED

APPLIED_TO_WORKTREE
→ Canonical Actual Change Set
   ├─ incomplete / unavailable → CANONICAL_CHANGE_SET_UNAVAILABLE Audit / Verification 차단 / APPLIED_TO_WORKTREE 유지
   └─ complete → M06 Post-Apply Diff Guardrail
                  ├─ deny  → Verification 실행 금지 / Audit 기록 / APPLIED_TO_WORKTREE 유지
                  └─ allow → Final Change Risk
                             → Verification Plan
                             → VERIFYING
                                ├─ VERIFIED
                                ├─ FAILED
                                └─ INCONCLUSIVE

VERIFIED
→ Canonical verified Patch artifact durability / integrity confirmed
→ Current Verification Policy Basis compatibility check
→ Current Approval / APPLY authorization check
   ├─ denied → Approval / Apply 차단 / APPLY_AUTHORIZATION_DENIED Audit / VERIFIED 유지
   └─ allowed → User confirms exact patch revision / hash / verification result / verification basis + approver / approval policy basis
                → Persist Approval Binding + APPROVED transition atomically / durably
                   ├─ persistence fail → CRITICAL_PERSISTENCE_FAILED / VERIFIED 유지 / Apply 금지
                   └─ durable → APPROVED
                                → Repository write lock / equivalent serialization
                                   ├─ acquire fail → Apply 중단 / APPLY_LOCK_UNAVAILABLE Audit / APPROVED 유지
                                   └─ acquired → Source / Policy / Authorization / Approval Binding Consistency Check + Apply 직전 기준점 재확인
                                                  ├─ Verification / Source MISMATCH → STALE_VERIFICATION
                                                  ├─ Approval binding invalid / authorization revoked → Approval 무효화 / VERIFIED 유지 / re-approval required
                                                  └─ MATCH → Persist Apply Attempt Intent / expected pre-post hashes
                                                             → Apply to Local Repository
                                                                ├─ apply command success → Post-Apply Result Integrity Check
                                                                │                          ├─ MATCH → APPLIED
                                                                │                          └─ MISMATCH → STALE_VERIFICATION / Audit / remediation required
                                                                └─ fail → Repository mutation 여부 확인
                                                                           ├─ provably no mutation → Audit / APPROVED 유지 / Recovery 가능
                                                                           └─ mutation 또는 unknown → Post-Apply Result Integrity Check
                                                                                                      ├─ MATCH → command failure와 실제 결과 불일치 Audit / APPLIED reconcile
                                                                                                      └─ MISMATCH / partial / unknown → STALE_VERIFICATION / remediation required
```

---

# 4. PATCH_APPLY_FAILED

Patch가 Worktree에 적용되지 않으면:

```text
PATCH_APPLY_FAILED
→ Risk / Verification 단계 진행 금지
→ Patch 재생성 시 새 revision 생성
```

M06 Pre-Apply Guardrail에서 차단된 경우는 Patch 적용 시도 자체가 발생하지 않았으므로 `PATCH_APPLY_FAILED`로 분류하지 않는다.
해당 Patch revision은 `PROPOSED` 상태를 유지하고 차단 사유를 Audit에 기록하며, Guardrail을 통과하기 전까지 Worktree Apply를 허용하지 않는다.

Safe Git Worktree 준비가 policy / environment 문제로 차단된 경우 Patch 적용 시도 이전이므로 `PATCH_APPLY_FAILED`로 분류하지 않고 `WORKTREE_PREPARATION_BLOCKED` 운영 오류를 기록하며 `PROPOSED`를 유지한다.

M06 Post-Apply Diff Guardrail에서 차단된 경우 Patch는 이미 Worktree에 적용된 상태이므로 `PATCH_APPLY_FAILED`로 분류하지 않는다.
해당 revision은 `APPLIED_TO_WORKTREE` 상태에서 Verification 진입을 차단하고, Patch 수정이 필요하면 새 revision을 생성한다.

---

# 5. Patch Revision Integrity

필수 식별자:

```text
patch_id
patch_revision
patch_hash
final_diff_hash
verification_result_id
verification_basis_id
approval_binding_id
```

Patch 내용이 변경되면:

```text
new patch_revision/hash
→ old Final Change Risk invalid
→ old Verification Plan invalid
→ old Verification Result invalid
→ old Approval invalid
→ M06 Pre-Apply Guardrail
→ Worktree re-apply
→ Canonical Actual Change Set
→ M06 Post-Apply Diff Guardrail
→ Final Risk
→ Verification Plan
→ Re-verify
```

규칙:

- `PATCH_APPLY_FAILED` 이후 Patch 수정 / 재생성 = 새 revision
- `FAILED` 이후 Patch 수정 = 새 revision
- `INCONCLUSIVE`에서 Patch 자체가 바뀌면 새 revision
- 동일 Patch에 부족한 검증만 추가하면 동일 revision 유지 가능
- `patch_hash` 또는 `final_diff_hash` 변경 시 새 Verification Result 필수
- `request_intent_id`가 변경되면 동일 Patch lineage의 revision 변경으로 취급하지 않고 새 `patch_id / change plan`을 생성한다. 서로 다른 사용자 요청을 하나의 Patch revision history에 혼합하지 않는다.
- 동일 `request_intent_id` 안에서 proposal base repository / branch / commit / source snapshot binding이 변경되면 textual patch가 같더라도 새 revision / hash를 생성하고 old Preliminary/Final Risk / Verification / Approval을 재사용하지 않는다.
- User Approval은 `patch_id / revision / patch_hash / final_diff_hash / verification_result_id / verification_basis_id / request_intent_id / approval_evidence_hash-or-reference`에 바인딩하며 이 중 하나가 변경되면 기존 Approval을 재사용하지 않는다.
- canonical verified Patch artifact가 durable Local Store에 저장되고 무결성이 확인되기 전에는 해당 revision을 Approval 대상으로 사용하지 않는다.
- Patch artifact는 intended write / create / delete / rename / mode / symlink / gitlink operation을 재현 가능한 형태로 표현해야 하며, 지원하지 않는 변경 유형은 생성 / 검증 단계에서 명시적으로 차단한다.
- patch artifact manifest와 적용 후 Canonical Actual Change Set이 일치하지 않으면 Verification으로 진행하지 않는다.
- Proposal base binding이 stale한 상태에서 Patch를 새 source에 자동 rebase / fuzzy-apply하여 기존 revision을 재사용하지 않는다. 재생성 또는 명시적 새 revision / 재분석 경로를 사용한다.

---

# 6. Isolated Worktree

필수 기능:

- canonical Proposal / baseline이 바인딩된 exact base commit / source snapshot에서 Temporary branch / Git worktree 생성
- 원본 working tree와 분리
- 기존 사용자 변경 보호
- 검증 실패 시 폐기 가능
- 최종 승인 전 main/default branch 직접 수정 금지
- OPTIMIZE baseline의 profiler / benchmark / build 부산물은 tracked source와 분리된 writable output 영역에 저장
- baseline 실행 전후 Worktree source 기준점을 비교하고 tracked source mutation이 발생하면 기존 baseline Evidence를 무효화한 뒤 reset / clean 또는 새 Worktree로 재구성하고 baseline을 재수행

Git worktree 생성 / checkout / status / diff / apply 등 Repository plumbing은 Safe Git Execution Profile을 사용한다.

필수 원칙:

- repository-controlled Git hook을 Host에서 실행하지 않는다.
- repository / local Git config의 external diff / textconv / clean-smudge-process filter / fsmonitor / pager / editor / credential helper 등 executable integration을 기본 비활성화한다.
- 필요한 Git integration은 pre-registered trusted adapter로 명시적으로 허용한 경우에만 사용한다.
- submodule initialization / update / fetch는 기본 비활성화하고, 필요 시 M08 Network Policy와 M06 Safe Git / Sandbox 정책을 통과한 local 또는 allowlisted internal source만 사용한다.
- parent Repository 내부의 nested Repository / submodule working tree는 별도 `repository_id`와 ACL이 확인되지 않으면 Worktree preparation / Patch target traversal 대상에 포함하지 않는다. parent Repository 권한만으로 nested Repository content를 자동 materialize / modify하지 않는다.
- system / global / repository config 중 실행 가능한 설정을 무조건 신뢰하지 않고 trusted config allowlist 또는 동등한 격리 정책을 적용한다.
- `.git/objects/info/alternates`, shared object directory, replace refs, graft-like object substitution 또는 partial-clone/promisor 설정이 Worktree materialization source를 바꿀 수 있는 경우 trusted object-store / Repository identity policy를 적용한다. Unauthorized external object source는 차단한다.
- Safe Git Worktree preparation 중 missing object에 대한 implicit network fetch를 허용하지 않는다. 필요한 object가 local 또는 explicitly allowlisted internal object source에 없으면 `WORKTREE_PREPARATION_BLOCKED`로 fail-closed 처리한다.
- Safe Git Execution Profile은 Worktree 생성 이전부터 적용하며, M06의 untrusted runtime Sandbox와 별개의 Host-side Git security boundary로 취급할 수 있다.
- hook / filter / submodule integration을 안전을 위해 비활성화한 결과 Worktree의 materialized source가 검증 대상 base source와 달라지는 경우 조용히 계속 진행하지 않는다. Worktree 생성 직후 expected base source snapshot / content hash와 materialized source를 비교하고, 불일치하면 `WORKTREE_PREPARATION_BLOCKED`로 fail-closed 처리한다.
- Repository가 Git LFS / custom filter / generated checkout integration 등 materialization에 필요한 integration을 요구하는 경우, pre-registered trusted integration 또는 별도 isolated preparation 경로가 없으면 Verification용 Worktree 준비를 완료된 것으로 간주하지 않는다. Public network fetch를 암묵적으로 허용하지 않는다.
- Temporary Worktree / branch에는 owner / patch / revision 식별자를 연결하고, process crash 후 orphan resource를 식별 / 정리할 수 있어야 한다. active worktree를 orphan으로 오인해 삭제하지 않는다.
- Worktree 준비 / Patch Apply 단계에도 configurable storage / file-count / single-file-size quota를 적용하여 Sandbox 진입 전 Host disk / inode 자원을 고갈시키는 Patch를 차단할 수 있어야 한다.
- Safe Git Execution Profile은 `GIT_DIR / GIT_WORK_TREE / GIT_CONFIG_* / pager / editor / credential / hook` 관련 Host 환경을 allowlist 방식으로 정리하여 호출자가 주입한 Git environment로 canonical Repository boundary를 우회하지 못하게 한다.

## Canonical Actual Change Set

Patch 적용 후 Final Risk / Guardrail / Verification의 기준 변경 집합은 단순 `git diff`가 아니라 `Canonical Actual Change Set`이다.

최소 포함 대상:

```text
tracked file modification
file deletion
rename / copy
new / untracked file created by Patch
Patch가 생성한 ignored path / file
file mode / type change
symlink creation / target change
submodule gitlink change
```

필수 원칙:

- Patch apply engine의 write / create / delete manifest와 Git 상태 / filesystem evidence를 함께 사용해 새 파일을 누락하지 않는다.
- 모든 Patch path는 canonical normalization 후 uniqueness를 검사하며, case-fold / Unicode normalization / platform short-name / symlink / path alias 등 실제 filesystem semantics상 동일 대상을 가리킬 수 있는 operation 충돌을 허용하지 않는다.
- 별도 Repository identity / ACL이 확인되지 않은 nested Repository / submodule working tree 내부 path를 Patch target으로 허용하지 않는다. Parent Repository의 gitlink 자체 변경과 nested working-tree content 변경을 구분한다.
- Change Set path 수집 / 비교는 사람이 읽는 `git diff` line parsing에 의존하지 않고 structured API 또는 NUL-safe / binary-safe representation을 사용한다. newline / leading dash / unusual byte sequence를 가진 filename이 option 또는 별도 record로 오인되지 않아야 한다.
- Patch Apply engine은 기존 symlink / junction 또는 Patch가 같은 revision에서 생성한 symlink를 따라 Repository root 밖 target을 write하지 않는다. 기존 ancestor / target type을 preflight하고 no-follow / dirfd-equivalent semantics 또는 동등한 안전한 적용 방식으로 canonical Worktree root 안에서만 filesystem mutation을 수행한다.
- hardlink / bind mount / mount-point / platform reparse-point 등 symlink 이외의 aliasing mechanism이 Repository root 밖 object 또는 보호 대상 file로 write side effect를 전달할 수 있는지 preflight한다. 안전성을 증명할 수 없으면 in-place write를 금지하고 atomic replacement 또는 fail-closed를 사용한다.
- Patch target의 device / inode-equivalent identity 또는 platform-safe file identity가 Repository 밖 보호 대상과 alias되어 있는 것이 탐지되면 기본 차단한다.
- `.gitignore` 때문에 숨겨진 Patch-created file도 Change Set에서 제외하지 않는다.
- baseline / build / profiler의 declared output artifact와 Patch가 만든 source change를 구분한다.
- 예상하지 않은 filesystem change가 발견되면 Change Set에 포함하거나 정책 위반 / source contamination으로 처리하며 조용히 무시하지 않는다.
- `final_diff_hash`는 이 Canonical Actual Change Set의 canonical representation / content hash에 바인딩된 값으로 정의한다.
- Change Set hash에는 `change_set_schema_version / hash_algorithm` 또는 동등한 canonicalization version을 함께 기록하며, semantics가 다른 버전의 hash를 직접 동일성 비교에 사용하지 않는다.
- canonical representation은 deterministic ordering과 path normalization rule을 가져야 하며, 동일 source state가 실행 순서에 따라 다른 hash가 되지 않아야 한다.
- binary / symlink / mode / gitlink 등 line diff로 충분히 표현되지 않는 변경도 `final_diff_hash`와 Guardrail / Risk Evidence에 포함한다.
- FIFO / device / socket 등 일반 source patch에서 지원하지 않는 special filesystem object는 기본 차단하며, 지원하려면 별도의 명시적 policy / sandbox capability가 필요하다.
- symlink 변경은 link target metadata를 Change Set에 포함하되 Repository root 밖 target content를 hash 목적으로 dereference하지 않는다.
- Canonical Actual Change Set을 완전하게 생성할 수 없으면 Final Risk / Verification으로 진행하지 않는다.

---

# 7. Apply-time Source Consistency

검증 당시 기록:

```text
verified_repository_id
verified_branch
verified_base_commit
verified_working_tree_diff_hash
verified_target_preimage_hash
verified_patch_id
verified_patch_revision
verified_patch_hash
verified_final_diff_hash
verification_result_id
verification_basis_id
```

적용 직전:

```text
Current Repository / Branch / Source / Verification Policy Basis
→ Compare with Verified Repository / Branch / Base / Verification Basis

MATCH
→ Apply 가능

MISMATCH
→ STALE_VERIFICATION
```

Source Consistency Check와 실제 Apply 사이의 동시 변경 위험을 fail-closed 방식으로 관리한다.
Knowledge Hub가 수행하는 Apply 작업끼리는 Repository write lock 또는 동등한 serialization으로 직렬화한다.
단, Knowledge Hub lock을 따르지 않는 외부 editor / process / Git command의 쓰기까지 절대적으로 차단한다고 가정하지 않는다.

필수 원칙:

- Source Consistency Check부터 Apply 완료까지 Knowledge Hub 내부 Apply 작업에는 Repository write lock 또는 동등한 serialization을 적용한다.
- lock은 process crash 후 영구 고착되지 않도록 OS advisory lock, lease / owner identity / expiry 또는 동등한 crash-recoverable mechanism을 사용한다. stale lock 회수 시 active owner 여부를 확인하고 임의 삭제만으로 동시 실행 안전성을 훼손하지 않는다.
- Apply 직전에 `verified_repository_id`, `verified_branch`, `verified_base_commit`과 현재 repository / branch / commit / working tree 기준점을 다시 확인한다.
- filesystem side effect 직전 현재 Repository `APPLY` 권한과 저장된 Approval binding의 `approver_user_id / approval_policy_version` 또는 동등한 승인 권한 기준을 재검증한다. 권한이 철회되었거나 기존 승인 자격이 더 이상 유효하지 않으면 side effect를 시작하지 않는다. Verification은 유효하지만 Approval만 무효인 경우 기존 Approval binding을 무효화하고 `VERIFIED` 상태에서 re-approval을 요구한다.
- Canonical Actual Change Set이 영향을 주는 각 target path의 preimage existence / type / content-or-link hash를 검증 당시와 비교한다. Git에서 ignored / untracked인 기존 파일도 Patch target이면 Source Consistency 대상에서 제외하지 않는다.
- 외부 프로세스의 동시 변경 가능성에 대비해 Apply 직전과 Apply 직후 source / diff 기준점을 검증한다.
- lock / serialization 확보에 일시적으로 실패하면 Apply를 중단하고 `APPLY_LOCK_UNAVAILABLE`을 Audit에 기록하되 Patch 상태는 `APPROVED`를 유지한다.
- repository / branch / source 기준점이 Apply 전에 변경된 경우 `STALE_VERIFICATION`으로 전환한다.
- current guardrail / risk threshold / verification policy bundle이 `verification_basis_id`와 다르고 명시적인 backward-compatible policy로 확인되지 않으면 기존 Verification을 재사용하지 않고 `STALE_VERIFICATION`으로 처리한다.
- backward-compatibility 판정은 LLM 임의 판단이 아니라 versioned trusted policy / deterministic compatibility rule 또는 authorized administrative decision에 근거하고, decision reference를 Audit에 남긴다.
- Patch가 M08 sensitive-file `modify` exception 또는 `sensitive_provenance` declassification decision에 의존한 경우 Apply 시점에 해당 decision의 user / repository / path-or-destination / operation / expiry / policy version 유효성을 다시 확인한다. 만료 / 철회 / scope mismatch이면 기존 Verification Basis를 stale로 간주해 `STALE_VERIFICATION`으로 처리하고 re-validation / re-approval을 요구한다.
- Source Consistency Check와 Apply를 서로 독립된 무보호 단계로 수행하지 않는다.
- 실제 filesystem side effect 전에 `apply_attempt_id / patch binding / pre_apply_source_hash / expected_post_apply_result_hash` 또는 동등한 Apply Intent를 durable Audit / Store에 기록하고 durable commit 성공을 확인한다. 필수 Audit / Store persistence가 실패하면 fail-closed로 Apply를 시작하지 않는다.
- 최종 Local Repository Apply도 검증된 canonical Patch artifact를 입력으로 사용하는 Safe Git / alias-safe apply profile을 사용한다. Repository hook / filter / editor / external command를 임의 실행하거나 LLM이 Apply command를 재생성하는 경로를 허용하지 않으며, Worktree에서 검증한 operation manifest와 동일한 write/create/delete/rename/mode semantics를 적용한다. symlink / junction뿐 아니라 hardlink / mount / reparse aliasing을 통해 Repository root 밖 side effect가 발생하지 않음을 확인한다.
- Apply command exit code만으로 성공을 확정하지 않는다. Apply attempt 이후 mutation이 없음을 입증할 수 없는 경우 Post-Apply Result Integrity Check를 수행한다.
- Apply command가 성공하더라도 실제 Repository 결과가 `verified_final_diff_hash` 또는 동등한 expected result hash와 일치한 경우에만 `APPLIED`로 전환한다.
- Post-Apply Result Integrity Check 결과(`post_apply_result_hash` 또는 동등한 evidence)를 Audit / Store에 연결한다.
- Apply 후 결과 불일치 / 외부 동시 변경 / partial mutation이 탐지되면 `APPLIED`로 전환하지 않고 Audit에 기록한 뒤 자동 재시도를 금지한다.
- partial apply 등으로 Repository가 dirty / inconsistent 상태가 된 경우 `STALE_VERIFICATION`으로 전환하고, repository remediation / clean 복구가 완료되기 전에는 자동 재분석 / 재검증 / Apply Recovery를 진행하지 않는다.
- 실제 Repository Apply 실패가 source mutation 이전의 원자적 실패라면 `APPROVED`를 유지하고 재시도할 수 있다. 재시도 시 lock과 Source Consistency를 다시 검사한다.
- lock을 획득한 이후 success / mismatch / exception / apply failure 등 모든 exit path에서 lock을 반드시 release한다.

---

# 8. Apply Recovery / Idempotent Resume

`APPROVED` 이후 프로세스 종료, 일시적인 lock 실패, 원자적 Apply 실패 등으로 실제 반영이 완료되지 않은 동일 revision은 Apply Recovery를 지원할 수 있어야 한다.

```text
APPROVED + not APPLIED
→ Restore canonical verified patch artifact
→ Verify restored artifact hash / revision / patch-artifact-schema integrity
→ Re-check Authorization / Approval Binding / Verification Basis
→ Re-acquire Repository Lock
→ Reconcile Current Repository State
   ├─ PRE_APPLY_MATCH        → Apply 재시도
   ├─ EXPECTED_POST_APPLY_MATCH → 이전 Apply 성공으로 reconcile → Post-Apply Integrity 확인 → APPLIED
   └─ OTHER / PARTIAL / UNKNOWN → STALE_VERIFICATION / remediation required
```

필수 규칙:

- Recovery는 동일 `patch_id / revision / patch_hash / final_diff_hash / verification_result_id / verification_basis_id / approval_binding_id`에 대해서만 허용한다.
- Recovery 시 현재 ACL / RBAC의 Repository Apply 권한과 기존 Approval binding의 현재 유효성을 다시 확인한다. Approval binding만 무효이고 Verification이 여전히 유효하면 기존 Approval을 무효화하고 `VERIFIED`에서 re-approval을 요구한다.
- 기존 사용자 승인을 새 승인으로 중복 기록하지 않는다.
- Recovery 시작 / lock 실패 / Apply 실패 / crash-reconciliation / 최종 적용 결과는 M09 Audit에 기록한다.
- 미완료 `APPLY_ATTEMPT_STARTED`가 존재하면 현재 source를 pre-apply expected state와 expected post-apply state 양쪽에 비교해 이미 성공한 Apply를 중복 실행하지 않는다.
- verified Patch artifact를 복원할 수 없거나 복원된 artifact의 hash / revision이 저장된 검증 기준과 다르면 Apply를 진행하지 않는다.
- Repository가 partial apply 등으로 remediation required 상태이면 clean / 복구가 완료되기 전 Recovery를 진행하지 않는다.

---

# 9. STALE_VERIFICATION

검증의 Source 또는 Security / Verification Policy 기준점이 더 이상 유효하지 않으면:

- 기존 Verification Result 무효
- 기존 `APPROVED` 무효
- 기존 사용자 승인 무효
- apply 금지
- partial apply / inconsistent source인 경우 먼저 repository remediation / clean 상태 복구
- clean / consistent Source가 확보된 뒤 현재 Source 기준 재분석
- 재검증
- 새 `VERIFIED`
- 사용자 재승인

---

# 10. Dirty Tree 연계

1차 구현에서는 MODIFY / OPTIMIZE / APPLY 시작 전에 dirty working tree를 차단한다.

Dirty snapshot 재현은 확장 기능이다.

---

# 11. 의존 모듈

- M01 CLI Approval
- M02 Repository Context
- M04 Final Risk
- M06 Pre-Apply Guardrail
- M07 Verification
- M09 Audit / Store

---

# 12. 성공 기준

- Patch는 M06 Pre-Apply Guardrail을 통과한 경우에만 Worktree에 적용된다.
- Patch가 원본보다 Worktree에 먼저 적용된다.
- Worktree / Git plumbing에서 repository-controlled hook / filter / external command가 Host에서 임의 실행되지 않는다.
- Safe Git integration 비활성화 때문에 Worktree source가 expected base source와 달라지는 경우 이를 탐지하고 Worktree 준비를 fail-closed로 차단할 수 있다.
- Patch 적용 후 새/untracked/ignored Patch-created file과 mode/symlink/gitlink 변경을 포함한 Canonical Actual Change Set을 생성할 수 있다.
- Patch 적용 실패와 검증 실패를 구분한다.
- revision이 바뀌면 이전 검증/승인이 무효화된다.
- 적용 직전 Source 변경을 탐지한다.
- stale verification은 원본 반영되지 않는다.
- Knowledge Hub 내부 Apply는 lock / serialization으로 직렬화하고, 외부 프로세스 변경은 apply 전후 source/result integrity check로 탐지한다.
- 일시적인 lock 획득 실패는 `STALE_VERIFICATION`으로 오분류하지 않고 `APPROVED` 상태에서 안전하게 재시도할 수 있다.
- crash 이후 stale lock / orphan worktree를 안전하게 식별하고 Recovery / cleanup할 수 있다.
- Repository identity / branch / source / target preimage / verification policy 기준점이 검증 당시와 동일한지 Apply 직전에 확인한다.
- `APPROVED` 상태에서 중단된 동일 revision의 Apply를 canonical verified patch artifact 기반으로 복구할 수 있다.
- Approval 전에 canonical verified Patch artifact의 durable persistence / integrity와 current policy / authorization eligibility를 확인한다.
- Apply side effect 직전 current APPLY authorization과 Approval binding 유효성을 재검증하고, Approval만 무효인 경우 Verification을 재사용 가능한 범위에서 `VERIFIED`로 되돌려 re-approval을 요구한다.
- durable Apply Intent / critical Audit persistence가 실패하면 Repository side effect를 시작하지 않는다.
- Repository Apply 결과가 verified expected result와 일치한 경우에만 `APPLIED`로 전환한다.
- Apply side effect 직후 crash가 발생해 state transition이 누락된 경우 expected post-apply state를 인식하여 중복 Apply 없이 `APPLIED`로 reconcile할 수 있다.
- partial apply가 발생하면 remediation / clean 완료 전 자동 재시도 / 재검증을 차단한다.
- OPTIMIZE baseline 실행 부산물이 Patch Canonical Actual Change Set에 혼입되지 않도록 Worktree source integrity를 확인한다.

---

# M06. Sandbox / Command Policy / agent_rule Harness

## 1. 책임

신뢰하지 않는 Repository 코드 및 LLM 실행 요청을
통제된 격리 환경에서 실행하고,
수정 정책과 명령 실행 경계를 강제한다.

---

# 2. Sandbox

기본 구조:

```text
Temporary Worktree
→ Isolated Sandbox
→ Dependency Restore
→ Test / Profiler / Benchmark
→ Result Collection
→ Dispose
```

필수 제한:

- CPU limit
- Memory limit
- execution timeout
- Internet egress BLOCK
- Repository 밖 파일 접근 제한
- writable directory 최소화
- writable storage / inode / file-count quota
- stdout / stderr / artifact output size limit
- 실행 종료 후 sandbox 폐기
- process crash 후 orphan sandbox / temp resource 식별 및 안전한 cleanup

Repository Code는 Trusted Runtime Code로 가정하지 않는다.
Sandbox process environment는 allowlist 방식으로 구성하며 Host / CLI 환경을 그대로 상속하지 않는다.

기본 차단 / 제거 대상 예:

```text
Knowledge Hub JWT / session credential
cloud provider credential
SSH_AUTH_SOCK / GPG agent socket
Host HOME credential files
package registry credential not required by runtime
arbitrary host environment secret
```

Dependency restore에 credential이 필요한 경우 restore 전용 최소 scope credential을 별도 phase에만 제공하고 Test / Profiler / Benchmark runtime으로 전달하지 않는다.
Sandbox image / volume에 production credential을 bake-in하지 않는다.

Sandbox에 제공되는 source view는 M08 Sensitive File Policy를 적용한 runtime-safe snapshot이어야 한다.

- Sensitive File은 기본적으로 Sandbox runtime에서 보이지 않게 제외한다.
- Test / Profiler / Build에 실제 민감 파일 접근이 필요한 경우 M08의 scoped `runtime-read` exception이 있어야 한다.
- runtime-read exception은 Retrieval / LLM context 또는 modification 권한을 자동으로 부여하지 않는다.
- production credential 대신 synthetic / test fixture를 사용할 수 있으면 이를 우선한다.
- Sandbox source view에는 `.git` file/directory 및 main Repository / worktree administrative metadata를 기본 노출하지 않는다. Git metadata가 테스트에 필요한 경우 sanitized read-only metadata view 또는 trusted Git proxy를 우선한다.
- Sensitive `runtime-read` 권한과 internal network allowlist를 동시에 부여하는 조합은 기본 금지하며, 불가피하면 별도의 combined exception / 최소 대상 / Audit을 요구한다.
- stdout / stderr / profiler / test artifact는 Local Store 또는 Web에 저장하기 전에 secret masking / detection을 적용한다.
- CLI / Web 표시용 텍스트는 terminal control sequence / ANSI escape / raw HTML / script-like markup을 신뢰된 UI instruction으로 해석하지 않도록 display-safe encoding / escaping을 적용한다. Raw Evidence가 필요한 경우 protected download / artifact 경로와 표시용 representation을 분리한다.
- XML / HTML / archive / structured test artifact parser는 외부 entity / template execution / path traversal 등 active-content 기능을 기본 비활성화하고 untrusted data로 처리한다.
- 안전한 redaction을 보장할 수 없는 결과는 일반 Audit payload에 저장 / 표시하지 않고 sensitive result로 격리하거나 폐기한다.

Sandbox Runtime Hardening 원칙:

- non-root 사용자 실행을 기본으로 한다.
- 불필요한 Linux capability는 제거한다.
- privilege escalation을 차단한다.
- process / PID 수를 제한한다.
- 가능한 경우 root filesystem을 read-only로 구성한다.
- Host PID / IPC / network namespace를 임의 공유하지 않는다.
- docker socket 등 Host 제어 인터페이스와 임의 Host Unix socket / device mount를 Sandbox에 노출하지 않는다.
- seccomp / AppArmor / SELinux 또는 동등한 runtime isolation policy를 적용할 수 있어야 한다.

구체적인 container runtime flag와 isolation profile은 Architecture / Detailed Design에서 확정한다.

Baseline 및 Patch Verification 실행은 검증 대상 source snapshot의 무결성을 보존해야 한다.

- 가능한 경우 source는 read-only mount / immutable snapshot으로 Sandbox에 제공한다.
- Test / Build / Profiler / Static tool이 output을 필요로 하면 source와 분리된 writable output / temp 영역을 사용한다.
- writable source copy가 불가피한 경우 실행 전후 Canonical Actual Change Set 대상 전체와 relevant source snapshot / `final_diff_hash` 기준점을 비교한다. tracked file뿐 아니라 Patch-created untracked / ignored source entry도 포함한다.
- Verification 실행으로 tracked source 또는 Patch-created untracked / ignored source entry가 변경되거나 예상 밖 source entry가 생성되면 해당 실행에서 얻은 Verification Evidence를 유효한 Patch 검증으로 사용하지 않는다.
- source mutation을 제거하고 exact verified Patch snapshot을 재구성한 뒤 Verification을 다시 수행한다.

OPTIMIZE baseline / benchmark 실행 부산물은 source Worktree와 분리한다.

- profiler / benchmark / coverage / build output은 별도 writable output directory에 기록한다.
- baseline 전후 relevant source snapshot hash를 비교하며 tracked source 외 relevant untracked source mutation도 확인한다.
- baseline 실행이 tracked source를 변경했거나 예상 밖 untracked artifact가 source diff에 혼입될 가능성이 있으면 해당 baseline Evidence를 무효화하고, reset / clean 또는 새 Worktree로 재구성한 뒤 baseline을 다시 수행한다.
- baseline 부산물을 Patch `Canonical Actual Change Set` 또는 `final_diff_hash`에 포함하지 않는다.

---

# 3. Offline Dependency Restore

허용:

```text
Prebuilt Sandbox Image
Local Package Cache
Internal PyPI / Maven / npm Mirror
Lockfile-based Existing Environment
Explicitly Allowlisted Internal Artifact Registry
```

금지:

```text
Public PyPI
Public npm Registry
Public Maven Central
GitHub Release Download
기타 Public Internet Download
```

Dependency 확보 불가 시 해당 검증은 `NOT_AVAILABLE`이 될 수 있다.

Dependency Restore와 untrusted Repository code 실행은 네트워크 경계를 분리한다.

- Dependency Restore는 Repository-controlled install / build hook을 Host 또는 일반 restore process에서 실행하지 않는 별도 restore phase 또는 동등한 통제 경로를 사용한다.
- prebuilt wheel / image / cache를 우선하며, dependency 자체의 build / install code 실행이 불가피한 경우 source Repository / credential을 마운트하지 않은 별도 dependency-builder sandbox에서 최소 권한으로 실행한다.
- Repository 자체의 install / build hook이 검증에 필수인 경우 dependency restore와 분리된 untrusted project sandbox에서 실행하고, 기본적으로 network egress 없이 수행한다.
- Internal package / artifact mirror 접근이 필요한 경우 restore / dependency-builder phase에만 최소 allowlist를 부여한다.
- Test / Profiler / Benchmark 등 untrusted runtime execution은 restore phase의 registry / artifact network 권한을 자동 상속하지 않는다.
- runtime 단계의 network는 기본 `NONE / BLOCK`이며, 테스트 자체에 내부 서비스 접근이 필요한 경우 별도의 명시적 allowlist와 Audit을 요구한다.
- Internal network allowlist는 단순 connectivity permission이지 임의 source / artifact 전송 권한이 아니다. 가능하면 synthetic / isolated test endpoint를 사용하고 destination / protocol / port / data-egress scope를 최소화하며, production control plane이나 범용 upload endpoint를 기본 허용하지 않는다.
- submodule dependency가 필요한 경우 자동 init / remote fetch를 기본 금지하고, pre-populated local submodule 또는 explicitly allowlisted internal source만 Safe Git profile / isolated restore 경로로 준비한다.
- required Verification 환경은 lockfile / resolved dependency set / artifact source(origin) / 가능하면 artifact digest 또는 동등한 immutable identifier를 기록하여 동일 version name의 mutable artifact를 조용히 동일 환경으로 취급하지 않는다.
- lockfile 없이 floating/latest resolution이 필요한 경우 이를 reproducibility limitation으로 기록하고 required Verification의 재현성을 보장할 수 없으면 `NOT_AVAILABLE` 또는 `INCONCLUSIVE`로 처리할 수 있어야 한다.

---

# 4. Command Execution Policy

LLM은 raw shell 명령을 직접 실행하지 않는다.
Repository source / comment / README / test output / profiler output 내부의 instruction-like text는 Tool permission 또는 policy authority로 취급하지 않는다. 이러한 Evidence에서 생성된 Tool Request도 동일한 Command Policy / Guardrail / Sandbox 경계를 통과해야 한다.

Tool 실행은 신뢰 경계에 따라 두 클래스로 분리한다.

```text
Qwen
→ Tool Request
→ Command Policy
   ├─ Trusted Non-Executing Adapter
   │    └─ Safe Git status / diff / repository introspection, pure source parser 등
   └─ Untrusted / Project-Aware Tool
        └─ Isolated Sandbox
```

Trusted Adapter는 Host에서 동작할 수 있지만 repository-controlled hook / filter / plugin / external command를 실행하지 않는 Safe Git / read-only profile이어야 한다.
Repository code / build hook / plugin 실행 가능성이 있는 도구는 Trusted Adapter로 분류하지 않는다.
Trusted Non-Executing Adapter도 untrusted filename / source / graph input을 처리하므로 configurable input-size / file-count / execution-time / memory bound와 fail-safe parser policy를 가져야 한다. 비실행 도구라는 이유만으로 Host resource exhaustion에 무제한 노출하지 않는다.

허용 후보:

```text
Trusted Safe-Git Adapter: git status / diff / change-set inspection
Canonical Change Set whitespace validator
python -m pytest
pytest
ruff
mypy
coverage
cProfile wrapper
tracemalloc wrapper
pre-registered project test command
pre-registered project build command
```

기본 차단 후보:

```text
sudo
ssh
scp
curl
wget
nc
rm -rf
mkfs
mount
docker socket direct access
host package manager mutation
arbitrary outbound network command
```

추가 원칙:

- Guardrail / Command allowlist / Sandbox capability / Network allowlist / Sensitive exception / policy compatibility와 같은 권한 부여 정책은 untrusted Repository source 또는 LLM output이 직접 self-authorize할 수 없다. Authority-bearing policy는 Repository 밖 trusted local policy store, signed/admin-controlled configuration 또는 동등한 보호 경계에서 관리한다.
- Repository 내부 config는 project test/build command, language metadata 등을 제안할 수 있으나 그 내용만으로 Host execution, network, credential, sensitive access, policy exception 권한을 확대하지 않는다. 권한 확대는 별도의 trusted registration / authorization을 요구한다.
- Repository code / project plugin / build hook을 실행할 가능성이 있는 Static Analysis / LSP / formatter / build-tool inspection도 M06 Command Policy / Sandbox 경로를 사용한다.
- Safe Git / pure source parsing처럼 repository-controlled executable integration을 완전히 차단한 도구만 Trusted Non-Executing Adapter로 Host 실행을 허용할 수 있다.
- Trusted Safe-Git Adapter는 object alternates / promisor / replace-ref 등 Repository object source를 trusted policy로 제한하고, status/diff/introspection 중 missing object를 이유로 임의 network fetch를 수행하지 않는다.
- 순수 source parsing처럼 Repository code를 실행하지 않는 분석은 read-only 도구로 분리할 수 있다.
- path argument는 canonicalize / realpath 검증 후 허용된 Repository / output root 내부인지 확인하고 symlink / junction escape를 차단
- hardlink / bind mount / mount-point / reparse-point 등 path canonicalization만으로 드러나지 않는 aliasing을 통해 Repository / Sandbox root 밖 protected object에 접근하거나 write하지 못하도록 filesystem identity / mount boundary를 검증하고, 안전성을 증명할 수 없으면 fail-closed
- 별도 ACL이 확인되지 않은 nested Repository / submodule working tree는 parent Repository Sandbox source view에 자동 포함하지 않음
- path list / Git change output은 structured / NUL-safe representation으로 전달하고, filename을 shell option / newline-delimited command fragment로 재해석하지 않는다. subprocess에 path를 전달할 때 option terminator 또는 동등한 API boundary를 사용한다.
- command + args 구조화
- raw shell string 금지
- shell metacharacter / command chaining / substitution 기본 차단
- project command는 pre-registered template만 허용
- command / args / exit code / duration은 Audit 기록
- Guardrail / Command Policy / Sandbox execution에는 사용한 `policy_version / command_policy_version / sandbox_profile_version` 또는 동등한 버전 식별자를 기록
- secret은 마스킹

---

# 5. agent_rule Harness

Guardrail은 Patch 적용 전과 Canonical Actual Change Set 생성 후 두 단계로 적용한다.

## Pre-Apply Guardrail

```text
Evidence First
→ lite / full policy
→ Minimum Change
→ Proposed Patch Inspection
→ Pre-Apply Guardrail
   ├─ ALLOW → M05 Worktree Apply
   └─ BLOCK → Worktree Apply 금지 / Audit 기록
```

Worktree 적용 전에 최소 다음을 검사한다.

- unresolved merge conflict
- `.env` 및 sensitive path 대상 변경 (M08의 scoped explicit modification exception이 없는 경우 기본 차단)
- `.git` / Git worktree administrative metadata 등 Repository control metadata 대상 변경
- Knowledge Hub의 authority-bearing local policy / credential / control-plane configuration을 Patch target으로 가장하거나 Repository path alias를 통해 수정하려는 변경
- FIFO / device / socket 등 기본 지원하지 않는 special filesystem object 생성
- credential / private key / token 등 민감 파일 대상 변경 (동일한 M08 정책 적용)
- 명백한 secret pattern 추가 (명시적 scoped exception이 없는 경우 기본 차단)
- 금지된 파일 경로 / 변경 범위
- Worktree / Host resource quota를 초과하는 patch bytes / file count / single-file size / path count
- 기존 symlink / junction / hardlink / mount / reparse-point 또는 Patch 내부 operation ordering을 이용해 canonical Worktree root 밖이나 보호 대상 object에 side effect를 전달하려는 target / ancestor path
- 별도 Repository identity / ACL이 확인되지 않은 nested Repository / submodule working tree 내부를 수정하려는 target (parent Repository의 gitlink metadata 변경은 별도 정책으로 판정)
- `sensitive_provenance`가 있는 Patch가 기존 보호 수준보다 낮은 일반 source / output 경계로 derived content를 이동시키는 경우 scoped declassification decision 존재 여부
- 정책상 허용되지 않은 대규모 또는 destructive change

Pre-Apply Guardrail에서 차단된 Patch는 Temporary Worktree에 적용하지 않는다.
차단은 `PATCH_APPLY_FAILED`와 구분하며, Patch 적용 시도 전 정책 차단으로 Audit에 기록한다.

Sensitive File modification은 기본 `BLOCK`이다.
예외는 M08이 승인한 explicit local policy exception이 현재 `user / repository / path / operation / policy version / expiry` 범위를 정확히 포함하고 실행 시점에도 유효할 때만 인정할 수 있고, 사용 사실을 M09 Audit에 기록한다.
Sensitive File modification exception은 해당 파일의 raw content를 Retrieval / LLM context에 포함할 권한을 자동으로 부여하지 않는다.
`sensitive_provenance`가 붙은 plan / patch / derived artifact를 일반 non-sensitive destination에 기록하는 것은 보호경계 downgrade가 될 수 있으므로, M08이 정의한 destination classification 또는 scoped `declassify` decision 없이 자동 허용하지 않는다. 동일 보호 범위 내에서 provenance를 유지하는 경우에는 declassification으로 간주하지 않을 수 있다.

## Post-Apply Diff Guardrail

```text
M05 Worktree Apply
→ Canonical Actual Change Set
→ Post-Apply Diff Guardrail
→ Command Policy
→ Test / Profiler / Benchmark
→ Verification
```

Canonical Actual Change Set 기준으로 최소 다음을 다시 확인한다.

- whitespace error
- 민감 파일 변경 여부 및 적용된 M08 scoped exception의 유효성
- secret pattern 유입 여부 및 허용 범위 초과 여부
- unresolved conflict marker
- Proposed Patch와 Canonical Actual Change Set 사이의 예상 밖 변경
- 새 / untracked / ignored Patch-created file 및 mode / symlink / gitlink 변경의 정책 위반 여부
- 허용된 Repository / Sandbox root 밖을 가리키는 symlink 또는 path traversal 위험
- `sensitive_provenance` derived content가 lower-protection destination으로 이동했는데 required declassification / reclassification policy decision이 없는 경우
- Canonical Actual Change Set 생성 실패 / 불완전 상태에서는 Guardrail을 성공으로 간주하지 않음

Pre-Apply 검사를 통과했더라도 Canonical Actual Change Set이 정책을 위반하면 Verification 실행을 차단하고 Audit에 기록한다.

---

# 6. 의존 모듈

- M05 Worktree
- M07 Verification Plan
- M08 Security
- M09 Audit

---

# 7. 성공 기준

- Test / Profiler / Benchmark가 Host에서 직접 실행되지 않는다.
- Host에서 허용되는 Git / source inspection은 Trusted Non-Executing Adapter에 한정되고 repository-controlled executable integration을 실행하지 않는다.
- Repository code / project plugin / build hook 실행 가능성이 있는 Static Analysis / LSP도 Host에서 직접 실행되지 않는다.
- CPU / Memory / execution timeout과 writable storage / inode / output size 제한이 실제 Sandbox 실행에 적용된다.
- 외부 egress가 기본 차단된다.
- Sandbox에서 허용된 Repository 범위 밖의 파일 접근이 차단된다.
- writable directory가 허용된 최소 범위로 제한된다.
- Public dependency download가 차단되고, dependency restore용 allowlist가 untrusted runtime 단계에 자동 상속되지 않는다.
- required Verification dependency의 lockfile / resolved origin / artifact digest-or-equivalent provenance를 기록하여 mutable dependency resolution을 조용히 동일 환경으로 취급하지 않는다.
- Trusted Non-Executing Adapter도 bounded resource / safe parser policy로 untrusted input을 처리한다.
- 실행 종료 후 Sandbox를 폐기할 수 있고 crash 후 orphan Sandbox도 active execution과 구분해 안전하게 정리할 수 있다.
- LLM 임의 shell 실행이 불가능하다.
- Repository source / config 또는 Patch가 Guardrail / Command / Sandbox / Network / Sensitive exception authority를 self-authorize하여 권한을 확대할 수 없다.
- Repository / tool output의 prompt injection 또는 instruction-like content가 Command Policy / Guardrail / Security Policy를 변경하거나 우회할 수 없다.
- 허용되지 않은 command를 차단한다.
- 민감 파일 수정 요청은 기본적으로 Worktree 적용 전 Pre-Apply Guardrail에서 차단하며, M08의 scoped explicit exception만 제한적으로 인정한다.
- Sensitive File은 Sandbox runtime에서 기본 비가시화하고, scoped `runtime-read` exception 없이 untrusted Repository code가 읽을 수 없게 한다.
- Host / CLI credential과 임의 environment secret이 untrusted Sandbox runtime으로 상속되지 않는다.
- stdout / stderr / profiler / test output에 포함된 secret이 일반 Audit / Web output으로 원문 노출되지 않도록 통제한다.
- Sensitive runtime-read와 network allowlist 같은 고위험 권한 조합은 각각의 개별 예외만으로 자동 결합하지 않는다.
- Sandbox runtime이 main Repository의 writable `.git` / worktree administrative metadata를 직접 조작할 수 없게 한다.
- Canonical Actual Change Set을 Post-Apply Diff Guardrail에서 재검사할 수 있다.
- Guardrail / Command / Sandbox 결과에 적용된 정책 / profile version을 추적할 수 있다.
- Sandbox가 non-root / least-privilege 원칙과 Host isolation 정책을 강제할 수 있다.
- path / symlink / junction / hardlink / mount / reparse alias를 통한 Repository / Sandbox root 밖 접근·write 우회를 차단하거나 안전성을 증명할 수 없으면 fail-closed 처리한다.
- 별도 ACL이 확인되지 않은 nested Repository / submodule working tree를 parent Repository 권한만으로 Sandbox source / Patch target에 포함하지 않는다.
- OPTIMIZE baseline 부산물이 tracked / relevant untracked source 또는 Patch Change Set을 오염시키지 않도록 검출 / 정리할 수 있다.
- Patch Verification 실행 전후 Canonical Actual Change Set 전체 / source snapshot / final diff integrity를 확인하고, 검증 도구가 tracked 또는 Patch-created untracked source를 변경하면 해당 Verification Evidence를 폐기 / 재실행할 수 있다.

---

# M07. Verification / Profiling / Benchmark

## 1. 책임

Patch가 실제로 안전하고 요구사항을 충족하는지 검증하고,
성능 변경은 실제 측정값으로 Before / After를 비교한다.

---

# 2. Verification Check Result

각 검증 항목:

```text
PASS
FAIL
INCONCLUSIVE
NOT_APPLICABLE
NOT_AVAILABLE
```

의미:

- PASS: 검증을 수행했고 요구 기준을 충족함
- FAIL: 검증을 수행했고 요구 기준을 충족하지 못함
- INCONCLUSIVE: 검증을 수행했거나 부분 수행했지만 변동성 / 재현성 / Evidence 불충분 등으로 PASS / FAIL을 확정할 수 없음
- NOT_APPLICABLE: 해당 프로젝트 / 변경에는 해당 검증이 의미상 적용되지 않음
- NOT_AVAILABLE: 적용 가능한 검증이나 환경/테스트 부족으로 실행 자체가 불가

`NOT_APPLICABLE`은 Verification 우회 수단으로 사용하지 않는다.

필수 원칙:

- required check를 `NOT_APPLICABLE`로 판정할 때는 명시적인 project metadata / test capability / deterministic rule / 승인된 policy에 근거해야 한다.
- Patch가 새로 추가·수정한 project metadata / test capability declaration만으로 required check를 스스로 `NOT_APPLICABLE`로 면제하지 않는다. Baseline inventory, trusted deterministic rule, independent capability evidence 또는 authorized policy decision으로 교차 확인한다.
- 단순히 테스트 파일을 찾지 못했다는 이유는 `NOT_APPLICABLE`이 아니라 원칙적으로 `NOT_AVAILABLE` 또는 추가 Evidence 필요로 처리한다.
- LLM은 `NOT_APPLICABLE` 후보와 rationale을 제안할 수 있지만 단독 authority로 required check를 N/A 확정하지 않는다.
- N/A 판정에는 `reason_code / rationale / evidence_reference / decision_authority` 또는 동등한 metadata를 남기고 M09 Audit에서 추적 가능해야 한다.

Patch 판정:

```text
any required FAIL
→ FAILED

no required FAIL
+ any required INCONCLUSIVE or NOT_AVAILABLE
→ INCONCLUSIVE

all required checks = PASS or NOT_APPLICABLE
→ VERIFIED 가능
```

---

# 3. Risk-based Verification Plan

Final Change Risk와 M03 acceptance criteria에 따라 최소 검증 범위를 생성한다.
Rule-based minimum required checks는 LLM / 사용자 편의 요청만으로 임의 제거하거나 낮은 수준으로 downgrade하지 않는다.
추가 check를 제안할 수는 있지만 required minimum을 제거하려면 명시적인 policy decision / rationale / Audit이 필요하다.

## LOW

```text
Canonical Change Set whitespace check (`git diff --check` + new/untracked change equivalent)
Static Check
Target Unit Test
```

## MEDIUM

```text
Canonical Change Set whitespace check (`git diff --check` + new/untracked change equivalent)
Static Check
Target Unit Test
Related Tests
Build Check
```

## HIGH

```text
Canonical Change Set whitespace check (`git diff --check` + new/untracked change equivalent)
Static Check
Target Unit Test
Related Unit Tests
Integration Tests
Build Check
필요 시 Regression Test
```

성능 변경은 Risk Level과 별개로 Before / After Benchmark를 추가한다.
MODIFY / OPTIMIZE의 behavior-changing 요청은 사용자 acceptance criteria / expected invariant가 최소 하나 이상의 Verification Check와 연결되어야 한다.
해당 behavior를 검증할 수 있는 executable / static Evidence가 존재하지 않으면 required intent check를 `NOT_AVAILABLE` 또는 `INCONCLUSIVE`로 처리하며 기존 regression check 통과만으로 요청 충족을 주장하지 않는다.
문서 / comment-only 등 behavior check가 의미상 적용되지 않는 변경은 M07의 엄격한 `NOT_APPLICABLE` 규칙을 따른다.

---

# 4. Verification Gate

Patch Verification 실행 전제:

```text
Worktree Apply = success
Canonical Actual Change Set = COMPLETE
Post-Apply Diff Guardrail = ALLOW
Final Change Risk / Verification Plan = available
```

위 선행조건을 충족하지 않으면 Verification을 시작하지 않는다.

```text
PATCH_APPLY_FAILED
→ verification 불가

VERIFYING
├─ VERIFIED
├─ FAILED
└─ INCONCLUSIVE
```

`VERIFIED`만 승인 대상으로 이동할 수 있다.

---

# 5. 자동 검증

Patch를 Temporary Worktree에 적용한 뒤 관련 테스트를 탐색한다.
Test / verification evidence에는 provenance를 구분한다. Provenance 분류는 LLM self-report가 아니라 trusted planner / test inventory / change-set evidence를 기준으로 결정한다.

```text
BASELINE_EXISTING_TEST
PATCH_MODIFIED_TEST
PATCH_ADDED_TEST
GENERATED_EPHEMERAL_CHECK
TRUSTED_EXTERNAL_HARNESS
```

Patch가 수정 / 추가한 테스트는 유용한 Evidence가 될 수 있지만 behavior-changing Patch의 유일한 성공 근거로 자동 승격하지 않는다.
가능한 경우 baseline에서 존재하던 target / related regression test와 trusted external / ephemeral acceptance check를 함께 사용한다.
Patch가 기존 required test를 삭제 / disable / skip하거나 test discovery / runner config를 변경해 검증 범위를 축소하면 Test Selection Integrity 위반으로 기록하고, 명시적 policy justification 없이는 `VERIFIED`로 통과시키지 않는다.
Patch가 required check를 실행하는 test runner / verification config / plugin / dependency / compiler / static toolchain 자체를 변경한 경우 그 Evidence provenance를 `PATCH_MODIFIED_VERIFICATION_TOOLCHAIN` 또는 동등하게 표시한다. 해당 변경된 toolchain만으로 Patch 성공을 증명하지 않고, 가능한 경우 baseline-pinned / trusted external harness 또는 독립된 secondary check로 교차 검증한다. 독립 검증이 required intent에 필요하지만 확보할 수 없으면 `INCONCLUSIVE`로 처리한다.
Verification은 `final_diff_hash`에 대응하는 exact source snapshot을 대상으로 수행해야 한다.
또한 Verification Result는 사용된 Final Risk threshold / Verification Plan / Guardrail / Command Policy / Sandbox profile의 policy bundle을 식별하는 `verification_basis_id` 또는 동등한 basis hash에 연결한다.
`verification_basis_id`에는 최소한 risk rule version + risk threshold version, required-check plan/version, `request_intent_id` 또는 protected request reference/hash + acceptance-criteria mapping hash/version, Guardrail / Command / Sandbox policy version, Verification에 사용된 security exception decision reference, required `NOT_APPLICABLE` decision reference를 포함하거나 무결성 연결해야 한다.
최종 CheckResult 집합과 required `NOT_APPLICABLE` / security exception / toolchain provenance decision이 확정된 뒤 Verification Result와 finalized `verification_basis_id`를 M09에 crash-consistent하게 연결하여 저장한다. 이 durable linkage가 실패하면 해당 결과를 Approval authority로 사용하지 않는다.

대상:

- Unit Test
- Integration Test
- Static Check
- Build Check
- Canonical Change Set whitespace check (`git diff --check` + new/untracked change equivalent)

실행하지 않은 검증을 실행했다고 주장하지 않는다.
Verification Plan은 baseline test inventory / post-patch test inventory 또는 동등한 Evidence를 비교해 required test가 예상 밖으로 사라지거나 skip되지 않았는지 확인할 수 있어야 한다.

Verification Environment Integrity 원칙:

- Verification 시작 전 source snapshot / `final_diff_hash` 기준점을 기록한다.
- Test / Build / Profiler / Static 실행 후 Canonical Actual Change Set의 모든 source entry와 relevant source snapshot이 변경되지 않았는지 확인한다. tracked file뿐 아니라 Patch-created untracked / ignored source도 포함한다.
- 검증 도구가 tracked source 또는 Patch-created untracked / ignored source를 변경하거나 예상 밖 source entry를 생성하면 해당 실행의 결과를 Patch 검증 Evidence로 확정하지 않고 `INCONCLUSIVE` 또는 execution-invalid로 기록한다.
- exact Patch snapshot을 복원한 뒤 해당 required check를 재실행할 수 있어야 한다.
- 반복 실행에서도 source mutation을 제거할 수 없으면 Patch 전체를 `INCONCLUSIVE`로 판정한다.

---

# 6. CPU / Runtime Profiling

1차 구현: Python

분석:

- CPU usage
- function execution time
- call count
- memory usage
- allocation
- peak memory

후보 도구:

```text
기본: cProfile
기본: tracemalloc
선택: py-spy
별도: process CPU time / CPU utilization collector
```

`cProfile`과 `tracemalloc`만으로 process-level CPU utilization을 직접 대체하지 않는다.
CPU usage가 Verification / Benchmark의 요구 지표인 경우 process CPU time 또는 CPU utilization을 수집할 별도 측정기를 사용한다.
구체 측정 도구와 sampling 방식은 Architecture / Detailed Design에서 확정한다.

`py-spy`는 다른 프로세스 추적에 추가 capability가 필요할 수 있으므로 1차 구현의 기본 Verification Sandbox 권한으로 강제하지 않는다.
필요 시 전용 Profiling Sandbox에서 최소 권한(`SYS_PTRACE` 등)만 별도로 허용하고, 일반 Test / Verification Sandbox와 권한 경계를 분리한다.

---

# 7. Memory / Allocation

Python 1차 구현은 Java식 Heap Dump보다 다음을 우선한다.

- tracemalloc snapshot
- allocation hotspot
- 객체 증가
- peak memory
- cache growth
- resource release 후보
- GC 부담 후보

---

# 8. Evidence-based Optimization

```text
Source
+
Potpie
+
Static Analysis
+
Profiler
+
Test
→ Qwen Recommendation
```

Profiler / Test / Static 결과 수집이 Qwen 최적화 판단보다 먼저다.

---

# 9. Before / After Benchmark

비교 항목:

- execution time
- average latency
- P95
- CPU
- peak memory
- allocation
- call count

원칙적으로 동일 조건을 사용한다.
Patch 자체가 dependency / runtime / compiler configuration 변경을 포함하는 경우 그 차이는 의도된 treatment로 명시적으로 기록하고, 그 외의 비의도적 환경 차이는 허용하지 않는다.
Before / After의 environment fingerprint가 비의도적으로 달라 비교 가능성을 확보할 수 없으면 required Benchmark를 `INCONCLUSIVE`로 판정한다.

Benchmark harness / dataset / measurement code가 Patch에 의해 변경되는 경우 그 provenance를 기록하고, 성능 개선을 증명하는 primary benchmark는 가능한 경우 Patch와 독립된 immutable / trusted harness를 사용한다.
Patch가 benchmark harness 자체를 바꾼 결과만으로 성능 향상을 확정하지 않는다.

Benchmark 결과는 단일 실행값만으로 성능 개선 여부를 확정하지 않는다.
동일 조건의 반복 측정을 기반으로 비교한다.

Benchmark가 해당 `OPTIMIZE` / 성능 변경의 Verification Plan에서 required check인 경우,
측정 변동성 또는 재현성 제한 때문에 개선 여부를 확정할 수 없으면 해당 Benchmark `CheckResult`를 `INCONCLUSIVE`로 기록하고 Patch 전체 Verification Result도 `INCONCLUSIVE`로 판정한다.
required benchmark의 판단 불가를 단순 reproducibility limitation만 표시한 채 `VERIFIED`로 통과시키지 않는다.

Benchmark가 required check가 아닌 보조 Evidence인 경우에는 결과와 reproducibility limitation을 함께 기록할 수 있다.

---

# 10. Benchmark Reproducibility

기록:

```text
dataset hash
runs
warmup
Python version
dependency version / lockfile hash / resolved artifact digest-or-origin reference
OS
CPU / GPU
memory
relevant environment
benchmark / environment fingerprint
dependency / runtime change as intended treatment 여부
base commit
patch / changed commit
```

조건이 동일하지 않으면 재현성 제한을 표시한다.

---

# 11. Patch Revision / Verification Basis 연계

Patch hash / final diff hash가 변경되면 이전 Verification Result를 재사용하지 않는다.
Approval / Apply 시점에 current risk threshold / guardrail / verification policy basis가 저장된 `verification_basis_id`와 달라지고 명시적 backward compatibility가 확인되지 않으면 기존 Verification Result를 재사용하지 않는다.
Policy backward-compatibility는 LLM 단독 판단이 아니라 versioned trusted policy / deterministic compatibility rule 또는 authorized administrative decision으로 판정하고 decision reference를 Verification Basis / Audit에 연결한다.

동일 Patch에서 부족한 검증만 추가하는 경우에만 기존 revision을 유지할 수 있다.

---

# 12. 출력

```text
VerificationPlan
AcceptanceCriteriaMapping[]
TestEvidenceProvenance[]
CheckResult[]
VerificationResult
ProfilerResult
BenchmarkResult
ReproducibilityMetadata
VerificationBasisReference
VerificationEnvironmentFingerprint
```

---

# 13. 성공 기준

- Risk와 acceptance criteria에 따른 최소 검증 계획을 만든다.
- behavior-changing Patch는 원 사용자 요청의 `request_intent_id` / protected request reference에서 유도된 acceptance criteria를 Verification Evidence와 연결하며, 검증 불가한 intent를 regression PASS만으로 충족했다고 주장하지 않는다.
- LLM / 사용자 요청만으로 deterministic required minimum check를 임의 downgrade하지 않는다.
- baseline existing test와 patch-modified / added / generated test provenance를 구분하고, Patch가 검증 범위를 자체적으로 축소 / 우회한 결과를 정상 PASS로 취급하지 않는다.
- primary performance claim은 가능한 경우 Patch와 독립된 benchmark harness로 검증한다.
- Worktree / Post-Apply Guardrail / Final Risk 선행조건을 우회한 Patch Verification을 허용하지 않는다.
- Verification 전후 Canonical Actual Change Set 전체 / source snapshot / final diff integrity를 확인하고, 검증 도구에 의한 tracked / Patch-created untracked source mutation이 있는 Evidence를 그대로 `PASS`로 사용하지 않는다.
- FAIL / INCONCLUSIVE / NOT_AVAILABLE을 올바른 Patch 상태로 반영한다.
- required check의 `NOT_APPLICABLE` 판정은 근거 / authority를 기록하며 LLM 단독 판단으로 Verification을 우회하지 않는다.
- whitespace / static validation은 Canonical Actual Change Set의 new/untracked Patch-created file까지 필요한 범위에서 포함한다.
- 성능 개선 여부를 단일 실행이 아닌 반복된 실제 측정값으로 판단한다.
- CPU usage가 요구 지표인 경우 별도 process-level CPU 측정기를 사용할 수 있다.
- 동일 조건 Before / After를 비교하며, 의도된 dependency / runtime 변경은 treatment로 명시적으로 기록한다.
- 비의도적 environment fingerprint 차이로 비교 가능성이 깨지면 required Benchmark를 `INCONCLUSIVE`로 처리한다.
- Benchmark reproducibility metadata를 저장한다.
- required Benchmark에서 개선 여부를 확정할 수 없으면 Verification Result를 `INCONCLUSIVE`로 판정한다.
- 보조 Benchmark의 재현성 제한은 결과와 함께 명시적으로 기록한다.
- patch hash / final diff hash 변경 시 이전 Verification Result를 재사용하지 않는다.
- Verification Result가 어떤 risk rule / threshold / acceptance-criteria mapping / verification / guardrail / command / sandbox policy basis에서 생성되었는지 식별할 수 있다.
- Verification에 사용된 주요 runtime / toolchain / dependency / command-template version을 environment fingerprint 또는 동등한 provenance로 기록할 수 있다.

---

# M08. Local-Only Security

## 1. 책임

사내 비밀 코드와 분석 데이터가 외부 서비스로 유출되지 않도록
Local-Only 실행 경계를 강제하고 검증한다.

---

# 2. 외부 서비스 금지

```text
OpenAI API       금지
Anthropic API    금지
Gemini API       금지
External Embedding 금지
External Web Search 금지
```

사용 대상:

```text
Local Repository
Local LLM
Local Embedding
Local Database
Local Vector DB
Local Code Graph
Local Profiler
Local Test Runner
```

---

# 3. Network Policy

```text
Internet Egress
DEFAULT = BLOCK

Internal Network
DEFAULT = DENY

Allow
= Explicit Allowlist Only
```

Git partial-clone / promisor / LFS / submodule / object-store 기능도 암묵적 예외가 아니며, local analysis / Safe Git introspection 중 자동 network fetch를 수행하지 않는다. 필요한 internal fetch는 명시적 allowlist / trusted control-plane 경로와 Audit을 요구한다.

Docker internal network / host firewall 등으로 강제한다.

---

# 4. Runtime Verification

다음 상태를 실행 시 확인한다.

```text
LLM Provider      LOCAL
Embedding         LOCAL
Repository        LOCAL
Code Graph        LOCAL
Telemetry         DISABLED
External API      DISABLED
Internet Egress   BLOCKED
Potpie Runtime    LOCAL
Potpie Provider   LOCAL ONLY
```

외부 LLM / embedding / provider 설정을 탐지하면 Code Intelligence 실행을 차단한다.
상태 조회 화면이나 CLI에서는 차단 원인을 경고로 표시할 수 있지만, Local-Only 필수 조건을 위반한 상태에서 분석 / Retrieval / LLM 실행을 계속하지 않는다.

---

# 5. Sensitive File Policy

Sensitive File은 기본적으로 ingestion / Retrieval / LLM context 및 untrusted Sandbox runtime source view에서 제외한다.
Repository 내부 symlink / junction을 통해 Sensitive File 또는 canonical Repository root 밖의 파일을 우회적으로 읽는 것도 동일하게 차단한다.
Sensitive classification은 path pattern만으로 한정하지 않고, high-confidence credential / private-key / token pattern 또는 trusted secret scanner가 탐지한 content도 policy input으로 사용할 수 있어야 한다. 탐지된 content를 LLM에 먼저 넣은 뒤 마스킹하는 방식으로 대체하지 않는다.
Git history / blame / historical diff를 Evidence로 사용할 때도 동일한 ACL / Sensitive Policy를 적용한다. 최근 변경 빈도처럼 metadata만 필요한 Risk factor는 raw historical source content를 LLM context에 넣지 않고 metadata Evidence를 우선한다.

Sensitive File modification은 기본 차단한다.

예외가 필요한 경우 명시적인 local policy allowlist와 권한 확인을 요구하며, 예외는 사용 시점마다 scope / expiry / current authorization을 재확인하고 사용 사실을 M09 Audit에 기록해야 한다.

Sensitive File 예외는 최소 다음 범위로 제한할 수 있어야 한다.

```text
user / role
repository
path / path pattern
operation (read-context / runtime-read / modify / declassify / remote-publish 등)
policy version
필요 시 expiry / one-shot scope
```

`read-context`, `runtime-read`, `modify`, `declassify`, `remote-publish` 예외는 서로 독립적으로 승인한다.
민감 파일 수정 예외가 존재한다는 이유만으로 raw file content를 Retrieval / LLM context 또는 Sandbox runtime에 포함하지 않는다.
`read-context` exception을 통해 Sensitive File content가 LLM context에 포함된 경우 그 content를 포함하거나 재구성할 수 있는 answer / analysis result는 sensitive context-derived result로 분류하고 일반 Audit / Web payload에 raw content를 자동 저장하지 않는다. 필요 시 protected Local Store / current ACL을 적용한다.
Sensitive `read-context` 또는 protected `runtime-read` 결과가 LLM / Planner / Patch Generator의 Evidence로 사용된 경우, 해당 downstream answer / plan / patch / derived artifact에는 `sensitive_provenance` 또는 동등한 보수적 label을 전파한다. 실제 secret 문자열의 완전한 정보흐름 추적을 전제로 하지 않으며, 명시적 declassification policy가 없는 한 해당 label을 자동 제거하지 않는다.
`sensitive_provenance`의 생성 / 전파 / 제거 결정은 LLM output의 self-report를 신뢰하지 않고 trusted orchestrator / policy layer가 Evidence lineage와 policy decision을 기준으로 관리한다. Model이 label 제거를 요청하거나 출력에서 생략해도 trusted metadata를 자동 해제하지 않는다.
Sensitive content에 대한 `read-context` 또는 `modify` 권한은 해당 값을 non-sensitive file / 일반 output / Remote Provider로 복사·공개하는 declassification 권한을 자동으로 부여하지 않는다.
`sensitive_provenance`가 붙은 derived content를 더 낮은 보호 등급의 local source / output으로 materialize하려면 destination classification을 유지하거나 별도의 scoped `declassify` decision을 요구한다. Provenance label 자체는 secret disclosure의 확정 증거가 아니라 보수적인 보호 신호이며, 명시적 declassification 없이 자동 downgrade하지 않는다.
Sandbox runtime에서 Sensitive File을 읽어야 하는 경우 별도의 scoped `runtime-read` exception과 권한 확인을 요구한다.
`runtime-read` exception을 사용한 실행 결과는 sensitive execution result로 분류하며, 단순 문자열 masking만으로 일반 결과와 동일한 공개 범위를 부여하지 않는다. Raw result가 보존되는 경우 일반 Audit payload와 분리된 보호 저장소 / ACL을 사용하고, 필요성이 없으면 폐기한다.
Sensitive runtime-read와 network allowlist를 동시에 요구하는 경우 별도의 combined policy decision / 최소 scope / Audit 없이는 허용하지 않는다.
Sensitive File 또는 `sensitive_provenance`가 연결된 derived content를 allowlisted internal Git Provider로 전송하는 Remote operation에는 scoped `remote-publish` authorization이 필요하다. Non-sensitive Remote operation도 Local Apply 승인에서 자동 파생되지 않으며 별도의 explicit remote intent / current Remote permission을 요구한다. Remote destination이 현재 보호 범위보다 낮거나 provenance downgrade가 발생하면 `remote-publish`와 별도로 scoped `declassify` decision도 요구한다. 두 권한은 서로 대체하지 않으며 사용 사실을 Audit에 기록한다.
M06 Guardrail / Sandbox는 이 정책 결정을 소비하며, 범위를 벗어난 context 제공 / runtime read / modification을 기본 차단한다.

예:

```text
.env
.env.*
*.pem
*.key
*.p12
*.pfx
credentials.json
secret/
secrets/
```

---

# 6. Logging Security

금지:

- API key 원문 저장
- token 원문 저장
- password
- private key
- 전체 source code를 Audit payload로 저장
- 민감 환경변수
- CLI / Web authentication credential, Remote Git provider credential 또는 Host agent socket을 LLM context / untrusted Sandbox runtime에 상속
- credential 가능성이 있는 raw profiler output
- secret redaction 전의 raw sandbox stdout / stderr / test artifact를 일반 Audit / Web payload로 저장

---

# 7. Potpie Security

Potpie는 Self-hosted only.

외부 cloud / provider / telemetry를 허용하지 않는다.

---

# 8. Sandbox Security

- Host 직접 실행 기본 금지
- Host / CLI / Remote Git provider credential / auth-agent socket runtime 상속 금지
- egress block
- allowlisted internal dependency source만 사용
- docker socket 직접 접근 금지
- destructive command 차단

---

# 9. 의존 모듈

- 전 모듈 공통
- 특히 M01 / M02 / M06 / M09

---

# 10. 성공 기준

- 외부 API 없이 핵심 기능이 동작한다.
- 외부 LLM / embedding / provider 설정이 탐지되면 Code Intelligence 실행을 차단한다.
- egress 차단 상태를 검증할 수 있다.
- untrusted Sandbox runtime이 Host / CLI credential / agent socket을 기본적으로 상속하지 않는다.
- 민감 파일 및 high-confidence secret content가 기본적으로 ingestion / Retrieval / LLM context에 유입되지 않도록 path + content classification을 적용할 수 있다.
- Git history / historical diff Evidence도 current ACL / Sensitive Policy를 우회하지 않는다.
- 민감 파일 modification은 기본 차단되며, 예외는 명시적 scoped allowlist + 권한 확인 + Audit 없이 허용되지 않는다.
- Sensitive File의 Retrieval / LLM context, Sandbox `runtime-read`, modification, `declassify`, `remote-publish` 예외를 서로 독립적으로 강제할 수 있다.
- scoped runtime-read exception이 없는 Sensitive File은 untrusted Sandbox runtime에서 기본 비가시화한다.
- Sandbox output의 secret이 일반 Audit / Web payload로 원문 노출되지 않도록 redaction / sensitive-result isolation을 적용할 수 있다.
- Sensitive runtime-read 또는 read-context를 사용한 downstream artifact에 보수적인 `sensitive_provenance`를 전파하고 ACL / Web / Remote 노출 범위를 제한할 수 있다.
- Sensitive runtime-read와 network allowlist의 고위험 조합은 명시적인 combined exception 없이 허용되지 않는다.
- symlink / junction을 통한 Sensitive File / Repository root 밖 source ingestion 우회를 차단한다.
- Potpie도 Local-Only로 검증된다.

---

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

---

# M10. Web Control Plane / Dashboard

## 1. 책임

CLI / Local Agent Core가 생성한 분석 결과와 운영 이력을
조회·시각화하는 Control Plane을 제공한다.

Web은 기본적인 코드 수정 실행면이 아니다.
Web 조회도 현재 사용자 Identity와 Repository ACL / RBAC를 적용하며, 과거에 접근 가능했던 Repository라는 이유만으로 현재 권한 없는 Graph / Patch / Audit / sensitive result를 노출하지 않는다.

---

# 2. 제공 영역

```text
Knowledge Hub
│
├── Knowledge
│   └── Existing Document RAG
│
└── Code Intelligence
    ├── Repositories
    ├── Architecture Graph
    ├── File / Function Graph
    ├── Change Impact
    ├── Risk
    ├── Performance
    ├── Benchmark History
    ├── Patch / Verification History
    ├── Audit Log
    └── Security / Local-Only Status
```

---

# 3. Repository Overview

표시 후보:

- Repository
- branch
- commit
- graph freshness
- Local-Only 상태
- 최근 analysis
- 최근 patch state

구체 UI는 상세설계에서 결정한다.

---

# 4. Graph

- Architecture / Dependency Graph
- File Graph
- Function / Call Graph
- Selected Symbol relation
- impacted callers / tests

---

# 5. Risk / Impact

- Preliminary Risk
- Final Change Risk
- Risk factor
- Impacted files/functions/tests
- threshold version

---

# 6. Performance

- profiler evidence
- CPU
- memory
- allocation
- latency
- Before / After
- benchmark reproducibility metadata

---

# 7. Patch / Verification History

Approval readiness / history를 표시하는 경우 최소 `Patch identity / Canonical Actual Change Set summary / original request intent·acceptance mapping summary / Final Risk / required Verification 결과 / INCONCLUSIVE·NOT_AVAILABLE 여부 / Sensitive·Security exception 여부 / Verification Basis`를 structured data로 표시할 수 있어야 한다. current ACL / sensitive policy가 허용하는 범위에서 exact canonical Patch / Change Set 상세를 protected viewer로 inspection할 수 있어야 한다. LLM 자연어 설명만으로 승인 근거를 대체하지 않는다. Web은 기본 Apply surface가 아니지만 CLI 승인과 동일한 Evidence를 조회 가능하게 제공한다. Approval Evidence view는 동일 `verification_result_id / verification_basis_id / request_intent_id`에 바인딩된 authoritative data만 조합하며, M08 ACL / redaction / sensitive provenance policy를 적용한다.

다음 상태를 모두 조회 가능해야 한다.

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

성공 건만 보여주는 Dashboard가 되면 안 된다.

추가로 lifecycle state와 별개인 다음 Apply 운영 상태 / 이벤트도 조회 가능해야 한다.

```text
APPLY_LOCK_UNAVAILABLE
Apply Recovery 진행 / 실패
Post-Apply Result Mismatch
Repository Remediation Required
Worktree Preparation / Canonical Change Set Blocked
Apply Crash Reconciliation
Stale Lock / Orphan Resource Recovery
Proposal Base Stale / Critical Persistence Failure / Approval Revalidation Required
Optional Remote Operation / Reconciliation
```

---

# 8. Audit Timeline

- request
- identity / ACL
- patch proposal
- revision
- state transition
- command execution
- verification
- approval
- source consistency
- apply / post-apply integrity
- apply recovery / remediation
- optional remote operation / reconciliation

---

# 9. Security Status

표시:

```text
LLM Provider
Embedding
Potpie
Telemetry
External API
Internet Egress
Sandbox Network Isolation
Sensitive Runtime-Read / Sensitive Provenance / Declassification / Remote-Publish Policy Status
Verification Policy Basis
Test / Benchmark Evidence Provenance
```

---

# 10. Web 제한

기본적으로 하지 않는다.

- 원본 source 직접 편집
- main/default branch 직접 수정
- 사용자 승인 없는 Patch 적용
- Host에서 임의 Test 실행

실제 변경은 CLI / Agent Core 경로를 사용한다.

Repository path / source snippet / diff / test output / Audit reason 등 untrusted content를 Web에 렌더링할 때는 기본 text escaping / output encoding을 적용한다. Repository가 제공한 HTML / SVG / Markdown / ANSI / script-like content를 신뢰된 UI markup으로 직접 실행하지 않는다. Raw artifact가 필요하면 current ACL이 적용되는 protected download / viewer 경로와 일반 Dashboard rendering을 분리한다.

---

# 11. 의존 모듈

- M09 Local Analysis Store
- 기존 Spring Boot authentication / authorization
- 기존 FastAPI AI/analysis layer
- Next.js UI

---

# 12. 성공 기준

- Graph / Risk / Performance 조회 가능
- Verification / Audit 이력 조회 가능
- CLI informed approval과 동일 basis에 바인딩된 request intent / acceptance mapping / Change Set / Risk / Verification Evidence를 안전하게 조회할 수 있다.
- FAILED / INCONCLUSIVE / STALE 상태도 표시 가능
- proposal base stale / Apply Recovery / lock unavailable / remediation required / post-apply mismatch / critical persistence failure / approval revalidation 상태와 Audit 근거도 표시 가능
- Local-Only runtime status 확인 가능
- 현재 Repository ACL에 따라 Graph / Patch / Audit / sensitive result 조회를 제한할 수 있다.
- Sensitive runtime-read / read-context / `sensitive_provenance` / declassification / remote-publish policy exception과 Verification Basis mismatch 이력을 raw secret 없이 확인할 수 있다.
- untrusted Repository / command output을 Web에서 active HTML / script로 실행하지 않고 안전하게 rendering할 수 있다.
- sensitive execution result는 current ACL과 protected-result policy를 통과한 경우에만 제한적으로 조회하고, 기본 Dashboard에는 raw payload를 노출하지 않는다.

---

# M11. Integration / Acceptance / Traceability

## 1. 책임

개별 모듈 요구사항이 하나의 CLI-first 제품 흐름으로 연결되는지 검증하고,
v1.10 원 요구사항과 모듈 사이 추적성을 제공한다.

---

# 2. 대표 Acceptance Flow

```text
1. Developer enters Repository
2. kh status
3. Identity Resolve
4. Canonical Repository Identity Resolve (non-executing Safe Git introspection)
5. Repository ACL / RBAC
6. Branch / Commit / HEAD / Git Operation / Dirty / Local-Only / Git Object Source / Nested Repository Boundary Check
    ├─ mutation-unsafe Repository state → REPOSITORY_STATE_BLOCKED / mutation STOP
    └─ NORMAL / supported state → continue
7. Dirty Tree Policy
8. Graph Freshness Check
9. kh optimize ...
10. Trusted Request Intent Capture → Query Planner + Acceptance Criteria Resolve / Mapping
11. Source / Potpie / Static Impact
12. Safe Git Execution Profile로 Temporary Worktree 생성 + expected base source materialization integrity 확인
    ├─ blocked / unsafe / materialization mismatch → WORKTREE_PREPARATION_BLOCKED / STOP
    └─ ready / expected base snapshot match → continue
13. M06 Command Policy / Sandbox Baseline
14. M07 Baseline Profiler / Benchmark
15. Baseline Worktree Source Integrity Check
    ├─ clean / unchanged → continue
    └─ mutation / artifact contamination → 기존 baseline Evidence 폐기 → reset / clean 또는 새 Worktree 생성 → baseline 재실행 / 재확인
16. New Pre-Patch Evidence가 있으면 Preliminary Risk Refresh
17. Qwen/local generator candidate → M05 Canonical Patch Proposal (`patch_id / revision / hash / request_intent / repository / branch / base commit / source snapshot` binding)
18. Proposal Base Consistency + M06 Pre-Apply Guardrail
    ├─ proposal base stale → PROPOSAL_BASE_STALE / re-analysis·proposal regeneration / Worktree Apply 금지
    ├─ Guardrail BLOCK → Worktree Apply 금지 / Audit 기록 / PROPOSED 유지
    └─ base match + Guardrail ALLOW → continue
19. Quota-bound / alias-safe(symlink / hardlink / mount / reparse) Patch Apply within canonical Worktree root
    ├─ fail → PATCH_APPLY_FAILED
    └─ success → APPLIED_TO_WORKTREE
20. Canonical Actual Change Set 생성
    ├─ INCOMPLETE / UNAVAILABLE → CANONICAL_CHANGE_SET_UNAVAILABLE / Verification 금지
    └─ COMPLETE → continue
21. M06 Post-Apply Diff Guardrail
    ├─ BLOCK → Verification 실행 금지 / Audit 기록
    └─ ALLOW → continue
22. Final Change Risk + Risk Rule / Threshold Version
23. Verification Plan + Acceptance Criteria Mapping Hash/Version + Baseline Test Inventory + provisional Verification Basis components
24. Command Policy / Sandbox Verification + Test Selection / Verification Toolchain Integrity / Evidence Provenance
25. Performance Benchmark if needed
26. Verification Source / final_diff Integrity Check
    ├─ unchanged → continue
    └─ mutation → 해당 Verification Evidence 폐기 / exact Patch snapshot 복원 / required check 재실행
27. Final CheckResult + finalized Verification Basis durable linkage / Verification Gate
    ├─ persistence fail → CRITICAL_PERSISTENCE_FAILED / Approval authority 생성 금지
    ├─ FAILED
    ├─ INCONCLUSIVE
    └─ VERIFIED
28. Canonical verified Patch artifact durable persistence / integrity confirmation
    ├─ persistence / integrity fail → CRITICAL_PERSISTENCE_FAILED 또는 VERIFIED_ARTIFACT_UNAVAILABLE / Approval 금지
    └─ durable / valid → continue
29. Persisted Verification Basis(risk rule/threshold + acceptance mapping + verification/guardrail/command/sandbox policy + N/A/security/toolchain provenance decisions)의 current trusted policy compatibility / required exception validity 확인
    ├─ incompatible / expired → re-validation / Approval 금지
    └─ compatible → continue
30. CLI Result
31. Informed User Approval Request with exact patch / revision / hash / verification result / verification basis / request intent + approver / approval policy basis
    ├─ Canonical Actual Change Set summary / original request intent·acceptance mapping / Final Risk / required Verification result 표시
    ├─ INCONCLUSIVE / NOT_AVAILABLE / Sensitive·Security exception 여부 표시
    ├─ LLM 설명문이 아닌 structured Evidence binding으로 approval 대상 식별
    └─ current ACL / sensitive policy 범위에서 exact canonical Patch / Change Set 상세 inspection 가능
32. kh apply + Current Identity / Repository Approval·APPLY 권한 확인
    ├─ denied → APPLY_AUTHORIZATION_DENIED / Approval·Apply 차단 / VERIFIED 유지
    └─ allowed → continue
33. Approval binding + immutable approval-evidence hash/reference + APPROVED transition atomic / durable persistence
    ├─ persistence fail → CRITICAL_PERSISTENCE_FAILED / VERIFIED 유지 / Apply 금지
    └─ durable → APPROVED
34. Repository write lock / equivalent serialization 획득
    ├─ fail → APPLY_LOCK_UNAVAILABLE Audit / APPROVED 유지
    └─ success → continue
35. Repository ID / Branch / Source / Target Preimage / Verification Policy Basis / Apply-relevant Exception Consistency Check
    ├─ MISMATCH → STALE_VERIFICATION
    └─ MATCH → continue
36. Apply 직전 verified repository / branch / base / target preimage / current source + Current APPLY Authorization / Approval Binding 유효성 재확인
    ├─ Source / Verification Basis MISMATCH → STALE_VERIFICATION
    ├─ Approval binding invalid / authorization revoked → Approval 무효화 / VERIFIED 유지 / re-approval required
    └─ MATCH → continue
37. Durable Apply Attempt Intent 기록 및 durable commit 확인 (attempt id / pre-apply hash / expected post-apply hash)
    ├─ persistence fail → CRITICAL_PERSISTENCE_FAILED / Apply side effect 금지
    └─ durable → continue
38. Verified canonical artifact 기반 Safe-Git / alias-safe(symlink / hardlink / mount / reparse) Repository Apply Command
    ├─ atomic fail without source mutation → Audit / APPROVED 유지 / Recovery 가능
    └─ command success 또는 mutation / unknown → Post-Apply Result Integrity Check
39. Post-Apply Result Integrity Check
    ├─ MATCH → APPLIED
    └─ MISMATCH / partial mutation → Audit / STALE_VERIFICATION / remediation required
40. lock을 획득한 모든 exit path에서 finally semantics로 lock release
41. Crash / Incomplete Apply Reconciliation
    ├─ PRE_APPLY_MATCH → APPROVED 유지 / Apply Recovery 가능
    ├─ EXPECTED_POST_APPLY_MATCH → 중복 Apply 없이 APPLIED로 reconcile
    └─ OTHER / PARTIAL / UNKNOWN → STALE_VERIFICATION / remediation required
42. Local Apply Outcome 분기
    ├─ APPLIED → Optional Remote Operation 검토 가능
    ├─ APPROVED + no mutation → Apply Recovery 가능
    └─ STALE / remediation required → Remote Operation 금지
43. APPLIED + explicit remote intent/trusted workflow authorization이 있는 경우에만 Optional Remote Operation
    ├─ exact patch / revision / post_apply_result_hash binding 확인
    ├─ verified canonical artifact / exact applied snapshot에서 immutable Remote source 생성 또는 동등한 hash-bound source materialization 확인
    ├─ current Repository ACL / Remote permission 확인 + provider credential은 trusted control plane에만 유지
    ├─ sensitive path 또는 `sensitive_provenance` 포함 시 필요한 M08 `declassify` + `remote-publish` policy authorization / destination protection 확인
    └─ Explicitly Allowlisted Internal Git Provider에서만 Merge / PR 허용
44. remediation required인 경우 clean / repository 복구 완료 전 자동 Retry / Re-analysis / Re-verification / Remote Operation 금지
45. STALE → old Verification / Approval invalid
46. clean / consistent Source 확보 후 Re-analysis / Re-verification / Re-approval
47. Lifecycle / Guardrail / Apply Attempt / Recovery / remediation events append to Audit
48. Web Dashboard displays history / Recovery / orphan cleanup evidence
```

---

# 3. Patch Modification Rule

FAILED 이후 Patch 수정 시:

```text
new patch revision/hash
→ previous Final Risk invalid
→ previous Verification Plan invalid
→ previous Verification Result invalid
→ previous Approval invalid
→ M06 Pre-Apply Guardrail
→ Safe Git Worktree apply
→ Canonical Actual Change Set
→ M06 Post-Apply Diff Guardrail
→ Final Risk
→ Verification Plan
→ Verify
```

INCONCLUSIVE에서 Patch 자체가 변경된 경우도 동일하다.

Patch가 그대로이고 부족한 검증만 추가할 때는 동일 revision을 유지할 수 있다.

---

# 4. Source Change Rule

```text
VERIFIED
→ Canonical verified Patch artifact durability / integrity confirmed
→ current Verification Basis / apply-relevant exception compatibility 확인
→ Current Identity / Approval·APPLY Authorization 확인
→ exact Patch / Verification Result / Verification Basis에 대한 User Approval
→ APPROVED
→ Repository write lock / equivalent serialization
→ Repository ID / Branch / Source / Target Preimage / Verification Basis Consistency Check
→ Apply 직전 repository / branch / source / target preimage + current APPLY Authorization / Approval Binding 유효성 재확인
├─ Source / Verification Basis MISMATCH
│    → STALE_VERIFICATION
│    → old Verification / Approval invalid
│    → partial / dirty inconsistency가 있으면 remediation / clean 복구
│    → clean / consistent Source 기준 re-analysis / re-verification / re-approval
├─ Approval binding invalid / authorization revoked
│    → old Approval invalid
│    → Verification이 여전히 유효하면 VERIFIED 유지 / re-approval
└─ MATCH
     → Durable Apply Attempt Intent
     → Apply
     → Post-Apply Result Integrity Check
        ├─ MATCH → APPLIED
        │          → 해당 Verification / Approval은 성공한 Apply의 historical evidence로 보존
        └─ MISMATCH / partial / unknown
             → STALE_VERIFICATION / remediation required
             → old Verification / Approval invalid
             → clean 복구 후 re-analysis / re-verification / re-approval

lock은 획득한 모든 exit path에서 finally semantics로 release한다.
```

---

# 5. Apply Recovery Rule

`APPROVED` 상태에서 실제 Repository Apply가 완료되지 않은 동일 revision은 새 사용자 승인 없이 Apply Recovery를 수행할 수 있다.

```text
APPROVED + not APPLIED
→ Restore verified Patch artifact
→ Verify restored artifact hash / revision integrity
→ Current Authorization / Approval Binding / Verification Basis / apply-relevant exception Recheck
→ Re-acquire Repository Lock
→ Reconcile Repository State against pre-apply + expected post-apply hashes
   ├─ PRE_APPLY_MATCH → Apply Retry → Post-Apply Result Integrity Check → MATCH일 때만 APPLIED
   ├─ EXPECTED_POST_APPLY_MATCH → crash-success reconcile → APPLIED
   └─ OTHER / PARTIAL / UNKNOWN → STALE_VERIFICATION / remediation required
```

일시적인 lock 획득 실패는 `STALE_VERIFICATION`이 아니며 `APPROVED`를 유지한다.
Recovery는 동일 `patch_id / revision / patch_hash / final_diff_hash / verification_result_id / verification_basis_id / approval_binding_id`에 한정한다.
Recovery 시작 전 현재 Identity / Repository APPLY 권한과 기존 Approval binding의 현재 유효성을 다시 확인한다. Approval만 무효이고 Verification이 유효하면 old Approval을 무효화하고 `VERIFIED`로 되돌려 re-approval을 요구한다.
Repository가 remediation required 상태이면 clean / 복구 완료 전 Recovery를 진행하지 않는다.
Recovery 중 Apply command가 실패하거나 mutation이 발생하면 일반 Apply와 동일한 post-apply integrity / remediation 규칙을 적용한다.

---

# 6. Remote Operation Rule

Local-Only 기본 원칙에서 원본 반영의 기본 종착점은 Local Repository다.

```text
MATCH
→ Apply to Local Repository

Merge / PR
→ Optional
→ Explicitly Allowlisted Internal Git Provider에서만 허용
→ Public Internet Git Provider는 기본 금지
```

Remote operation은 Local Repository lifecycle이 `APPLIED`인 경우에만 허용한다. Local `kh apply` 승인만으로 Remote publish / PR / Merge 권한을 자동 부여하지 않으며, 별도의 explicit remote intent 또는 사전에 승인된 trusted workflow policy와 current Remote permission이 필요하다.
Remote operation은 해당 `patch_id / revision / post_apply_result_hash`에 바인딩된 exact applied result만 대상으로 하며, Local Apply 이후 발생한 추가 working-tree 변경을 자동 포함하지 않는다.
Remote source는 기본적으로 verified canonical artifact / exact applied snapshot에서 생성한 별도 branch 또는 commit-like immutable snapshot을 사용한다. Remote branch/commit materialization도 repository-controlled hook / editor / credential helper를 임의 실행하지 않는 Safe Git / trusted control-plane 경로를 사용한다. 현재 working tree를 Remote source로 사용하는 구현은 `Git clean` 자체를 필수 의미로 해석하지 않고, Local Apply 이후 추가 변경이 없으며 Canonical Actual Change Set / `post_apply_result_hash`와 exact applied snapshot이 일치함을 다시 확인해야 한다. Local Apply로 인해 working tree에 의도된 Patch 변경이 존재한다는 이유만으로 Remote source를 부정하지 않으며, 의도된 applied result 외 추가 변경이 하나라도 있으면 Remote operation을 차단한다.
Remote 실행 시에도 현재 Repository ACL / Remote permission을 다시 확인한다.
`APPROVED`, `STALE_VERIFICATION`, remediation required 또는 Apply Recovery 대기 상태에서는 Remote operation을 시작하지 않는다.
Remote operation은 M08 Network Policy와 동일한 allowlist 정책을 사용하며, 허용되지 않은 외부 Git provider로의 source / diff 전송을 금지한다.
Remote 기능을 구현하는 경우 side effect 전 `remote_operation_id` / exact applied result binding / provider target을 durable Audit에 기록하고, provider가 지원하면 idempotency key 또는 동등한 중복 방지 기준을 사용한다. timeout / crash 등으로 remote result가 불명확하면 provider 상태를 reconcile한 뒤에만 재시도하며 동일 PR / Merge request를 중복 생성하지 않는다.

---

# 7. 모듈 추적표

| v1.10 / Derived Safety 요구영역 | 담당 모듈 |
|---|---|
| CLI-first / Informed Approval | M01 + M10 + M11 |
| Identity / ACL | M01 |
| Local Repository / Dirty Tree / Nested Repository ACL Boundary | M02 + M01 + M05 + M06 |
| File / Function Graph | M02 |
| Potpie Local-Only | M02 + M08 |
| Code Explain | M03 |
| Query Planner | M03 |
| Untrusted Evidence / Prompt-Injection Boundary | M03 + M06 |
| Impact / Blast Radius | M04 |
| Risk Score / Risk Rule Versioning | M04 + M07 |
| Preliminary / Final Risk | M04 |
| Patch Proposal / Candidate Canonicalization | M05 + M03 |
| Patch Revision Integrity | M05 |
| Durable Verified Artifact / Approval Binding / Apply Recovery | M01 + M05 + M09 |
| Worktree / Safe Git | M05 + M06 |
| Safe Worktree Materialization Integrity | M05 + M11 |
| Alias-safe(symlink/hardlink/mount/reparse) / Quota-bound Patch Apply | M05 + M06 + M11 |
| Canonical Actual Change Set | M05 |
| Source Consistency / STALE | M05 |
| Sandbox | M06 |
| Command Policy / Trusted Policy Authority Boundary | M06 + M08 + M09 |
| agent_rule | M06 |
| Verification States | M07 |
| Request Intent / Acceptance / Verification Basis Traceability | M03 + M07 + M09 |
| Risk / Acceptance-based Verification | M07 + M03 |
| Verification Evidence Provenance / Test Selection Integrity | M07 + M09 |
| Profiling / Memory | M07 |
| Benchmark | M07 |
| Local-Only Runtime / Sensitive runtime-read | M08 + M06 |
| Sensitive Provenance / Declassification / Remote-Publish Policy | M06 + M08 + M09 + M10 + M11 |
| Audit / Crash-Consistent Critical Persistence | M09 + M05 |
| Local Analysis Store | M09 |
| Web Dashboard | M10 |
| End-to-End Acceptance | M11 |

---

# 8. 구현 우선순위 제안

이 순서는 요구사항 변경이 아니라 구현 의존성을 기준으로 한 권장 순서다.

```text
Phase 1
M01 CLI skeleton
M01/M08 Safe Repository Identity / non-executing Git introspection baseline
  - canonical repository identity
  - repository discovery에서 hooks / filters / executable Git integration 금지
M08 baseline security boundary
  - Local provider enforcement
  - External provider block
  - Basic Internet egress block
  - Sensitive File default exclusion / runtime environment sanitization
M02 Repository Context
M09 basic local store / audit

Phase 2
M02 Graph Adapter
M03 Planner / Explain
M04 Impact / Preliminary Risk

Phase 3
M05 Patch / Worktree / Lifecycle
M06 Sandbox / Command Policy / agent_rule

Phase 4
M04 Final Risk
M07 Verification / Profiling / Benchmark

Phase 5
M08 Local-Only runtime hardening
  - Runtime verification
  - Stronger isolation / policy validation
  - Security status integration
M10 Web Control Plane

Phase 6
End-to-End Acceptance hardening
```

---

# 9. v1.10 동결 원칙

이 모듈 문서에서 해결하지 않는 설계사항:

- DB 제품 선택
- API endpoint path
- ORM
- CLI framework
- IPC 방식
- exact Risk weight
- exact UI layout
- exact JWT issuing mechanism

위 항목은 Architecture / Detailed Design 문서에서 확정한다.
