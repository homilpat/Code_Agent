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
