# Knowledge Hub Code Intelligence v1.10 — FINAL FREEZE v7 Changelog

이번 최종 라운드는 기존 기능 범위를 확장하지 않고, 구현 시 우회/오판 가능성이 남아 있던 경계를 정리했다.

## 최종 보강 사항

- Informed Approval Contract
  - request intent / acceptance mapping / Change Set / Final Risk / required verification / security exception / Verification Basis를 structured evidence로 표시
  - 사용자가 실제 본 approval evidence snapshot의 immutable hash/reference를 Approval binding에 연결
  - exact canonical Patch / Change Set을 current ACL / sensitive policy 범위에서 inspection 가능
- Request Intent Traceability
  - trusted orchestrator가 모델 변환 전에 immutable request envelope / `request_intent_id`를 고정
  - Verification Basis와 Approval까지 request intent / acceptance mapping을 추적
  - `request_intent_id` 변경은 새 Patch revision이 아니라 새 `patch_id / change plan`으로 분리
- Patch Proposal Ownership / Base Binding
  - M03는 intent/routing, M05는 candidate Patch의 canonical Proposal 수용/식별을 담당
  - Proposal을 repository / branch / base commit / source snapshot / preliminary-risk reference에 binding
  - base가 stale하면 `PROPOSAL_BASE_STALE`로 Worktree Apply 차단 및 재분석/새 revision 요구
  - patch artifact schema/version과 generator provenance 기록
- Nested Repository / Submodule ACL Boundary
  - parent Repository ACL을 nested Repository source/history/modification 권한으로 자동 상속하지 않음
  - nested Repository boundary를 RepositoryContext에 표시하고 별도 repository identity/ACL 없이는 traversal/patch/sandbox 포함 금지
- Filesystem Alias Safety
  - symlink/junction 외 hardlink, bind mount, mount-point, reparse-point, case/Unicode/platform alias까지 고려
  - 안전성을 증명하지 못하면 atomic replacement 또는 fail-closed
- Git Object / Materialization Boundary
  - external alternates/shared object store/replace refs/partial-clone/promisor를 trusted policy로 제한
  - local analysis / Safe Git introspection 중 implicit network fetch 금지
  - sparse checkout/materialization scope를 source completeness에 반영
- Verification Bypass Hardening
  - Patch가 수정한 project metadata만으로 required check를 `NOT_APPLICABLE`로 self-exempt하지 못함
  - baseline/trusted rule/independent evidence/policy로 교차 확인
- Recovery Consistency
  - M01 Apply Recovery를 M05/M11과 동일하게 PRE_APPLY / EXPECTED_POST_APPLY / OTHER-PARTIAL 3분기 reconcile
- Remote Operation Boundary
  - Local `kh apply` 승인이 Remote PR/Merge 권한으로 자동 승격되지 않음
  - 별도 explicit remote intent 또는 trusted workflow authorization + current Remote permission 필요
  - exact applied immutable source를 Safe Git/trusted control-plane 경로로 materialize
