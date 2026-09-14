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
