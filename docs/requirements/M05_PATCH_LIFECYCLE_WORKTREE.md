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
