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
