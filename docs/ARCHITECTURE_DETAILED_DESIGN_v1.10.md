# Knowledge Hub Code Intelligence — Integrated Architecture / Detailed Design v1.10

> Status: Reviewed Integrated Architecture / Detailed Design  
> Scope: M01 ~ M11 공통 구현 기준 및 상세설계 진입 기준  
> Basis: v1.10 모듈별 요구사항 최종 통합본 및 M01~M11 개별 요구사항  
> 목적: 요구사항 수준에서 남겨둔 DB / class-interface / Git adapter / filesystem hardening / Sandbox / policy DSL / persistence / module contract를 실제 구현 가능한 설계 수준으로 구체화한다.

---

# 1. 문서 목적

본 문서는 Knowledge Hub Code Intelligence v1.10의 Architecture / Detailed Design 단계에서 사용할 공통 기준을 정의한다.

기존 요구사항 문서는 다음과 같은 구현 세부를 상세설계에서 확정하도록 의도적으로 남겨두었다.

- DB 제품 / ORM
- CLI framework
- IPC 방식
- exact API schema
- Safe Git adapter 구현
- filesystem mutation hardening
- `openat2` / `O_NOFOLLOW` 등 OS별 path security
- Docker / container / microVM isolation profile
- Sandbox runtime flag
- policy DSL
- artifact persistence 방식
- crash consistency / recovery mechanism
- class / interface boundary

본 문서에서는 위 항목에 대한 **Architecture 결정과 Detailed Design 공통 구현 원칙**을 확정하고, M01~M11의 상세설계를 **동일 문서 안의 모듈 섹션으로 확장하는 단일 Source of Truth**로 사용한다. 동일 내용을 반복하는 M01~M11 별도 상세설계 문서는 기본적으로 만들지 않는다. 단, SQL DDL, JSON Schema, seccomp/AppArmor profile, policy schema처럼 기계적으로 관리할 산출물은 별도 부속 파일로 분리할 수 있다.

단, 기존 요구사항에서 정의한 사용자 기능 / 보안 / 검증 intent를 변경하지 않는다.

---

# 2. 설계 원칙

## 2.1 Trusted Authority와 LLM 역할 분리

LLM/Qwen은 다음 역할만 수행한다.

```text
Planner candidate
Explanation
Patch candidate
Optimization recommendation
```

다음 authority-bearing identifier / binding / policy decision은 LLM이 생성하거나 덮어쓸 수 없다.

```text
request_intent_id
repository_id
proposal base binding
patch_id
patch_revision
patch_hash
final_diff_hash
verification_result_id
verification_basis_id
approval_binding_id
apply_attempt_id
policy decision
security exception
sensitive provenance
```

위 값은 Trusted Orchestrator / M01~M09의 deterministic trusted code에서 생성 / 주입한다.

Repository source / README / comment / runtime output / LLM output은 Evidence이며 policy authority가 아니다.

---

## 2.2 CLI-first 유지

Primary Work Surface는 CLI다.

```text
CLI
→ Identity
→ Canonical Repository Identity
→ ACL / RBAC
→ Repository Context
→ Planner / Risk
→ Patch / Sandbox / Verification
→ Approval
→ Local Apply
```

Web Control Plane은 기본적으로 조회 / 시각화 / inspection surface로 유지한다.

---

## 2.3 Fail-Closed

다음 상황에서는 추정으로 계속 진행하지 않는다.

```text
Repository identity 불명확
ACL 미확인
Source snapshot 불완전
Graph freshness 불명확
Proposal base mismatch
Canonical Change Set 불완전
Verification basis persistence 실패
Sensitive policy decision 불명확
Apply preimage mismatch
Post-Apply result mismatch
Filesystem alias safety 입증 실패
Sandbox isolation 불충분
```

필요한 경우 `BLOCK / INCONCLUSIVE / NOT_AVAILABLE / STALE_VERIFICATION / remediation required`로 전환한다.

---

# 3. 상위 Component Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                         USER                                 │
│                                                              │
│          CLI                         Web                     │
│          M01                         M10                     │
└───────────┬───────────────────────────┬──────────────────────┘
            │                           │
            └─────────────┬─────────────┘
                          ▼
                Trusted Orchestrator
                request_intent_id
                auth / policy context
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
        M02             M03/M04           M09
 Repository/Graph      Planner/Risk      Store/Audit
          │               │                ▲
          │               ▼                │
          │              M05───────────────┤
          │        Patch / Worktree        │
          │               │                │
          │               ▼                │
          │              M06───────────────┤
          │      Command / Sandbox         │
          │               │                │
          │               ▼                │
          └──────────────►M07───────────────┘
                   Verification

     M08 Local-Only Security / Policy Engine
     ───────────────────────────────────────
     M01~M10 전 경로에 cross-cutting policy / runtime security decision 제공
```

M11은 위 전체 경로에 대한 Acceptance / Traceability / E2E contract를 담당한다.

---

# 4. Runtime / Process Architecture

## 4.1 Frontend / Control Plane

```text
frontend-nextjs
└── Next.js Web UI

backend-spring
└── Spring Boot
    ├── existing authentication
    ├── session / JWT integration
    ├── Repository RBAC
    ├── Web Control Plane API
    └── current authorization re-check
```

## 4.2 Code Intelligence Agent

```text
code-agent
└── Python
    ├── CLI
    ├── identity
    ├── repository
    ├── planner
    ├── impact / risk
    ├── patch / worktree
    ├── sandbox / harness
    ├── verification / benchmark
    ├── security policy
    ├── audit
    └── local store
```

## 4.3 LLM / RAG

```text
rag-fastapi
└── FastAPI + Local LLM / Local Embedding
```

외부 LLM / embedding / web search provider는 Code Intelligence 경로에서 기본 금지한다.

## 4.4 Target Language Architecture

Code Agent의 **구현 언어는 Python**이지만, 분석·수정 대상 언어를 Python으로 고정하지 않는다. Target language support는 trusted registry와 adapter capability로 분리한다.

```text
Target Repository
      │
      ▼
LanguageSupportCatalog
      │
      ├─ StructuralLanguageRegistry     # M02가 소비
      │    └─ StructuralLanguageAdapter
      │         ├─ Python
      │         ├─ ECMAScript (TS/TSX/JS/JSX/MJS/CJS)
      │         └─ Java
      │
      └─ LanguageToolchainRegistry      # M06/M07가 소비
           └─ LanguageToolchainAdapter
                ├─ Python toolchain
                ├─ Node/TypeScript toolchain
                └─ JVM toolchain
```

두 adapter는 권한 경계를 분리한다.

```text
StructuralLanguageAdapter
→ source parse / import / symbol / syntax relation
→ Repository code / build hook / plugin 실행 금지

LanguageToolchainAdapter
→ static/test/build/profile에 필요한 structured ToolRequest 생성
→ raw shell 생성 금지
→ 실제 실행은 M06 Command Policy + Sandbox만 허용
```

지원 상태는 **구조 분석(Structural) / 툴체인 실행 계획(Toolchain) / 최종 지원 상태(Effective)** 를 분리해 표현한다. 하나의 parser가 존재한다는 이유만으로 해당 언어를 end-to-end `ACTIVE`로 표시하지 않는다.

| Target language | Detailed Design target | Structural | Toolchain | Effective | 현재 저장소 구현 상태 |
|---|---|---|---|---|---|
| Python | v1 primary | **PARTIAL** | **PARTIAL** | **PARTIAL** | stdlib AST graph / Python explain은 구현됐지만 아직 `StructuralLanguageRegistry/Adapter` migration·conformance가 완료되지 않음. 제한된 pytest command compile/Docker plan은 존재하지만 실제 Sandbox execution backend와 full Verification/Apply 경로는 아직 없음 |
| TypeScript / JavaScript | phase 2 | **PLANNED** | **PLANNED** | **PLANNED** | adapter 계약만 설계, runtime 등록/실행 구현 없음 |
| Java | phase 3 | **PLANNED** | **PLANNED** | **PLANNED** | adapter 계약과 profiling/verification 경로만 설계, runtime 등록/실행 구현 없음 |
| 기타 | extension | **UNSUPPORTED** 또는 **PARTIAL** | **UNSUPPORTED** | **UNSUPPORTED/PARTIAL** | SourceSnapshot에는 포함될 수 있으나 structural/toolchain capability가 없으면 완전 지원으로 승격하지 않음 |

현재 구현이 Python 중심이라는 사실을 숨기지 않는다. 현재 CLI `doctor`의 Python 분석 capability가 `PYTHON_STATIC_PARTIAL_LINUX_ONLY`이고 Sandbox/Approval/Apply가 아직 불가하므로 **Python의 effective language support는 `PARTIAL`** 로 본다. 현재 Python AST/graph 기능은 존재하지만 새 `StructuralLanguageAdapter/Registry` 계약으로의 migration·trusted registration·conformance가 아직 완료되지 않았으므로 Structural layer도 현재는 `PARTIAL`이다. 해당 migration과 conformance가 완료된 뒤에만 Structural status를 `ACTIVE`로 승격한다. TS/JS/Java adapter가 구현되기 전에는 해당 언어의 behavior-changing Patch를 완전 검증했다고 주장하지 않으며 required capability가 없으면 M07에서 `NOT_AVAILABLE`/`INCONCLUSIVE`로 처리한다.

---

# 5. IPC Boundary

1차 설계는 다음을 기본으로 한다.

```text
Spring Boot
    │
    │ localhost-only HTTP 또는 Unix Domain Socket
    ▼
Python Code Agent
```

권장 우선순위:

```text
Linux local deployment
→ Unix Domain Socket 우선

Cross-platform / 초기 구현 단순화
→ localhost-only HTTP 가능
```

외부 network bind는 기본 허용하지 않는다.

---

# 6. Local Store / DB Architecture

## 6.1 DB 제품

1차 구현은 SQLite를 기본 선택으로 한다.

이유:

- Local-Only Agent Store에 적합
- single-node / local control-plane 중심
- transaction 지원
- WAL 지원
- crash consistency 구현 가능
- append-only Audit + materialized state를 하나의 DB에서 atomic하게 갱신 가능
- 별도 DB server dependency 불필요

기본 pragma:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
```

SQLite는 구현 단순화를 위한 1차 선택이며, PostgreSQL이 요구사항상 필수라는 의미는 아니다.

운영 제약:

- DB 파일은 local filesystem에 둔다. NFS/SMB 등 network filesystem 위 WAL 운용은 지원 대상에서 제외한다.
- writer는 Local Store service/repository layer를 통해 직렬화하며, 각 모듈이 SQLite connection을 임의 생성해 직접 갱신하지 않는다.
- busy timeout / transaction retry는 bounded policy로 제한하며, critical persistence가 timeout으로 확정되지 않으면 fail-closed 처리한다.
- schema migration에는 monotonically increasing `schema_version`을 사용하고 downgrade를 자동 수행하지 않는다.

---

## 6.2 DB + Artifact Store 분리

대형 / 민감 artifact를 DB BLOB에 전부 저장하지 않는다.

```text
~/.knowledge-hub/
├── db/
│   └── knowledge-hub.db
│
├── artifacts/
│   ├── patch/
│   ├── verification/
│   ├── benchmark/
│   └── protected/
│
├── worktrees/
├── sandbox/
└── locks/
```

DB는 artifact metadata 및 integrity binding을 저장한다.

```text
artifact_id
relative_path
content_hash
size
classification
schema_version
created_at
```

---

## 6.3 Artifact Durable Write

Filesystem과 SQLite를 하나의 ACID transaction으로 묶을 수 없으므로 staged durable-write protocol을 사용한다.

```text
1. artifact temp file write
2. fsync(temp file)
3. atomic rename(temp → final)
4. fsync(parent directory)
5. DB transaction에서 artifact metadata/integrity binding + authority state commit
6. commit 성공 후 artifact = READY
```

4와 5 사이 crash가 발생하면 파일만 존재하는 orphan artifact가 생길 수 있으므로 startup reconciliation / periodic cleanup에서 DB reference가 없는 artifact를 안전하게 식별한다. 반대로 DB가 READY를 가리키는데 artifact가 없거나 hash가 다르면 `CRITICAL_PERSISTENCE_FAILED`로 취급하고 authority를 노출하지 않는다.

Approval / Apply authority를 형성하는 artifact는 durable file + DB integrity binding이 모두 완료되기 전에는 authoritative state로 승격하지 않는다.

## 6.4 Artifact Protection / Retention

- artifact root directory는 owner-only 권한을 기본으로 한다(Linux 0700, file 0600 또는 OS 동등 권한).
- `SENSITIVE / PROTECTED` raw artifact를 보존해야 하는 경우 AES-256-GCM 등 authenticated encryption을 사용하고, master key는 SQLite나 Repository에 저장하지 않고 OS credential store에 보관한다. 보호 키를 확보할 수 없으면 raw protected artifact persistence는 fail-closed하거나 정책상 허용되는 경우 즉시 폐기한다.
- 일반 Audit payload에는 raw secret/source 전체를 저장하지 않는다.
- ephemeral sandbox filesystem / raw runtime output은 Evidence 추출·분류 후 즉시 dispose하는 것을 기본으로 한다.
- verified Patch artifact, approval evidence, apply/recovery integrity evidence는 해당 lifecycle/history가 유지되는 동안 무결성 검증 가능하게 보존한다.
- Repository purge / retention 설정은 versioned trusted local policy로 관리하고, policy 변경도 Audit한다.

---

# 7. M09 중심 DB Domain

최소 aggregate / table 후보:

```text
repositories
repository_roots
repository_context_snapshots
source_snapshots

graph_snapshots
graph_provider_runs

request_intents
acceptance_criteria
acceptance_mappings

patches
patch_revisions
patch_artifacts
canonical_change_sets

risk_results
risk_factors

verification_plans
verification_results
verification_checks
verification_basis

approval_bindings
apply_attempts

security_decisions
sensitive_artifacts

sandbox_runs
command_executions

profiler_results
benchmark_results

audit_events
```

---

## 7.1 Patch Table 예시

```sql
CREATE TABLE patches (
    patch_id TEXT PRIMARY KEY,
    request_intent_id TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

```sql
CREATE TABLE patch_revisions (
    patch_id TEXT NOT NULL,
    revision INTEGER NOT NULL,

    patch_hash TEXT NOT NULL,
    patch_schema_version TEXT NOT NULL,

    proposal_base_commit TEXT NOT NULL,
    proposal_source_snapshot_hash TEXT NOT NULL,

    lifecycle_state TEXT NOT NULL,

    final_diff_hash TEXT,

    PRIMARY KEY (patch_id, revision),
    FOREIGN KEY (patch_id) REFERENCES patches(patch_id)
);
```

구체 schema는 M09 Detailed Design에서 확정한다.

---

# 8. Audit / State Crash Consistency

Audit는 append-only event store 성격을 유지한다.

```text
audit_events
```

최소 필드 후보:

```text
event_id
aggregate_type
aggregate_id
event_type
event_version
repository_id
user_id
payload_json
idempotency_key
created_at
```

Lifecycle current state는 별도의 materialized state로 유지할 수 있다.

중요 state transition은 반드시 같은 transaction으로 처리한다.

예:

```text
BEGIN IMMEDIATE

INSERT audit_event
UPDATE patch_revision lifecycle_state

COMMIT
```

다음 영구 상태를 허용하지 않는다.

```text
state는 바뀌었는데 event가 없음

event는 있는데 state는 이전 상태
```

Apply / Verification / Approval은 idempotency key 또는 동등한 중복 방지 식별자를 갖는다.

---

# 9. Shared Domain Layer

모듈 구현 전 공통 domain package를 먼저 만든다.

```text
code-agent/
└── core/
    ├── ids.py
    ├── enums.py
    ├── errors.py
    ├── hashing.py
    ├── canonical.py
    ├── clock.py
    └── result.py
```

Typed ID 후보:

```text
UserId
CommandRequestId
RepositoryId
RepositoryRootId
RepositoryContextId
SourceSnapshotId
GraphSnapshotId
GraphProviderRunId
GraphNodeId
GraphEdgeId
RequestIntentId

PatchId
PatchRevision

VerificationResultId
VerificationBasisId

ApprovalEvidenceId
ApprovalBindingId
ApplyAttemptId

ArtifactId
AuditEventId

PolicyDecisionId
SandboxRunId
```

UUID 문자열을 arbitrary code에서 직접 생성하기보다 typed wrapper / factory를 사용한다.

Target language 공통 값도 shared domain으로 둔다.

```python
class LanguageId(StrEnum):
    PYTHON = "PYTHON"
    TYPESCRIPT = "TYPESCRIPT"
    JAVASCRIPT = "JAVASCRIPT"
    JAVA = "JAVA"
    UNKNOWN = "UNKNOWN"


class LanguageFamily(StrEnum):
    PYTHON = "PYTHON"
    ECMASCRIPT = "ECMASCRIPT"
    JVM = "JVM"
    UNKNOWN = "UNKNOWN"


class LanguageCapability(StrEnum):
    STRUCTURAL_PARSE = "STRUCTURAL_PARSE"
    SYMBOL_RESOLUTION = "SYMBOL_RESOLUTION"
    TEST_DISCOVERY = "TEST_DISCOVERY"
    STATIC_CHECK = "STATIC_CHECK"
    BUILD = "BUILD"
    UNIT_TEST = "UNIT_TEST"
    INTEGRATION_TEST = "INTEGRATION_TEST"
    CPU_PROFILE = "CPU_PROFILE"
    MEMORY_PROFILE = "MEMORY_PROFILE"
    BENCHMARK = "BENCHMARK"


class LanguageSupportStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PARTIAL = "PARTIAL"
    PLANNED = "PLANNED"
    UNSUPPORTED = "UNSUPPORTED"
```

상태 의미:

```text
ACTIVE
→ 해당 layer의 adapter가 구현·trusted registry 등록·conformance 확인까지 완료됨

PARTIAL
→ 일부 capability는 실제 사용 가능하지만 해당 layer 또는 end-to-end 필수 capability가 빠져 있음

PLANNED
→ Detailed Design target일 뿐 runtime capability가 아님

UNSUPPORTED
→ 해당 language/layer에 trusted adapter contract 구현 또는 등록이 없음
```

동일 언어라도 `structural_status`, `toolchain_status`, `effective_status`가 다를 수 있다. 실행 시에는 등록된 adapter + conformance result + toolchain availability가 실제 capability authority다.

---

# 10. Integrated Detailed Design 작성 포맷

M01~M11은 **별도 파일이 아니라 이 master 문서 안에서** 동일한 structure의 모듈 섹션으로 작성한다. 별도 문서 복제는 traceability drift를 만들기 쉬우므로 기본 금지한다.

```text
Mxx Architecture / Detailed Design

1. Design Goals
2. Component Architecture
3. Package / Directory Layout
4. Domain Model
5. Class / Interface Design
6. DB Schema
7. Adapter Design
8. State Machine / Sequence
9. Security Boundary
10. Failure / Recovery
11. Configuration / Policy
12. API / IPC Contract
13. Observability / Audit
14. Test Strategy
15. Requirement Traceability
16. Implementation Order
```

모듈별로 필요하지 않은 항목은 `N/A`로 명시하되, 임의로 생략하지 않는다. SQL DDL / OpenAPI / JSON Schema / policy schema / seccomp profile처럼 실행·검증 가능한 산출물은 `design/appendices/` 아래 별도 파일로 두고 본문에서 version/hash로 참조한다.

---

# 11. M01 — CLI / Identity / Repository Access Detailed Design

## 11.1 Design Goals

M01은 Code Intelligence의 **trusted entry boundary**다. 코드 분석 자체를 수행하지 않고, 모든 CLI 요청에 대해 다음 순서를 강제한다.

```text
CLI Invocation
→ Identity Establishment
→ Minimal Canonical Repository Identity Resolution
→ Current Repository ACL / RBAC
→ Authorized Repository Context Load
→ Command-specific Safety Gate
→ Downstream Module Dispatch
```

설계 목표:

- 보호된 Repository의 source / graph / history / branch detail을 ACL 이전에 읽지 않는다.
- 사용자 입력 path가 아니라 stable `repository_id`와 canonical physical root mapping으로 권한을 판단한다.
- CLI와 Web이 동일한 authorization authority / permission semantics를 사용한다.
- `kh verify`와 `kh apply`가 M05~M09의 lifecycle / verification / policy gate를 우회하지 못한다.
- `kh apply`는 exact authoritative Evidence를 사용자에게 표시한 뒤에만 informed approval을 생성한다.
- 기존 Approval을 영구 capability로 취급하지 않고 Apply / Recovery 시 current authorization을 다시 확인한다.
- Repository path / symbol / Audit reason / tool output 등 untrusted 문자열을 terminal markup / ANSI control sequence로 실행하지 않는다.
- credential 원문을 Audit / log / exception message에 저장하지 않는다.

M01이 직접 담당하지 않는 것:

```text
source parsing / graph build             → M02
request intent / planner                 → M03
risk                                     → M04
patch mutation / repository apply        → M05
sandbox command execution                → M06
verification gate                        → M07
sensitive / Local-Only policy authority  → M08
durable state / audit                    → M09
```

---

## 11.2 Component Architecture

```text
Typer CLI
   │
   ▼
CliApplication
   │
   ├─ SafeTerminalRenderer
   ├─ IdentityService
   │    ├─ CredentialStore
   │    ├─ SessionIdentityProvider
   │    └─ OsUserMappingIdentityProvider (optional)
   │
   ├─ MinimalRepositoryIdentityResolver
   │    └─ M02 Safe Repository Inspector port
   │
   ├─ RepositoryAuthorizationService
   │    └─ existing Spring auth/RBAC authority adapter
   │
   ├─ AuthorizedRepositoryContextLoader
   │    └─ M02 Repository Context port
   │
   ├─ CommandSafetyGate
   │    ├─ RepositoryMutationStateGate
   │    ├─ VerificationReadinessPort
   │    └─ ApprovalEligibilityPort
   │
   ├─ ApprovalCoordinator
   │    ├─ ApprovalEvidenceAssembler
   │    ├─ VerificationBasisCompatibilityPort
   │    ├─ ApprovalEvidenceStorePort
   │    └─ M09 ApprovalPersistencePort
   │
   ├─ ApplyEntryPort / ApplyRecoveryPort
   │    └─ M05
   │
   └─ AuditPort
        └─ M09
```

`CliApplication`은 orchestration만 담당한다. Repository filesystem mutation, Git apply, Sandbox execution을 직접 수행하지 않는다.

---

## 11.3 Package / Directory Layout

```text
code-agent/
├── cli/
│   ├── app.py
│   ├── commands/
│   │   ├── status.py
│   │   ├── explain.py
│   │   ├── impact.py
│   │   ├── modify.py
│   │   ├── profile.py
│   │   ├── optimize.py
│   │   ├── verify.py
│   │   ├── apply.py
│   │   └── history.py
│   ├── renderer.py
│   ├── exit_codes.py
│   └── selectors.py
│
├── identity/
│   ├── models.py
│   ├── service.py
│   ├── providers.py
│   ├── credential_store.py
│   └── os_mapping.py
│
├── access/
│   ├── authorization.py
│   ├── permission_matrix.py
│   └── command_gate.py
│
└── approval/
    ├── models.py
    ├── evidence.py
    ├── coordinator.py
    └── prompt.py
```

공통 ID / enum / error는 `core/`를 사용하며 M01 package에서 중복 정의하지 않는다.

---

## 11.4 CLI Command Contract

Python CLI framework는 **Typer**로 확정한다.

기본 명령:

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

공통 옵션:

```text
--repo PATH
    기본값 cwd.
    Repository 밖에서 실행하거나 다른 Repository를 지정할 때 사용한다.

--no-color
    terminal capability에 상관없이 plain structured output을 요청한다.
```

Patch selector가 필요한 명령은 optional selector를 지원한다.

```text
kh verify [--patch PATCH_ID] [--revision N]
kh apply  [--patch PATCH_ID] [--revision N]
```

selector를 생략한 경우 **정확히 하나의 eligible revision만 존재할 때만** 자동 선택한다. 0개면 readiness error, 2개 이상이면 `AMBIGUOUS_PATCH_SELECTION`으로 차단하고 임의의 latest revision을 선택하지 않는다.

`kh apply` v1은 informed interactive approval을 기본으로 하며 일반적인 `--yes` / environment-variable auto approval은 제공하지 않는다. 향후 non-interactive approval이 필요하면 별도의 signed/trusted approval workflow로 설계하고 현재 CLI confirmation을 우회하지 않는다.

Command별 최소 권한:

| Command | Minimum permission | 추가 gate |
|---|---|---|
| `status` | `REPOSITORY_VIEW` | current ACL 후 상세 status 조회 |
| `explain` | `CODE_ANALYZE` | M02/M03 read-only |
| `impact` | `CODE_ANALYZE` | M02/M04 read-only |
| `modify` | `CHANGE_PROPOSE` | NORMAL mutation state + clean policy |
| `profile` | `RUNTIME_ANALYZE` | M02 dirty/runtime policy + M06/M08 |
| `optimize` | `CHANGE_PROPOSE` + `RUNTIME_ANALYZE` | NORMAL mutation state + clean policy |
| `verify` | `PATCH_VERIFY` | exact Verification readiness gate |
| `apply` | `PATCH_APPROVE` + `PATCH_APPLY` | exact Approval / Apply gate |
| `history` | `HISTORY_VIEW` | current ACL + protected-result filtering |

위 permission enum은 Code Agent의 canonical permission vocabulary다. 기존 Spring role/RBAC는 `RepositoryAuthorizationService` adapter에서 이 vocabulary로 매핑한다. Repository 내부 config가 permission mapping을 변경할 수 없다.

Command dispatch contract:

| Command | Downstream port | Primary result |
|---|---|---|
| `status` | M02 Repository Context + M08 Runtime Security + M02 Graph freshness | `RepositoryStatusView` |
| `explain` | M03 | explanation + Evidence refs |
| `impact` | M03/M04 | impact/risk result |
| `modify` | M03 → M04 → M05/M06 | proposed Patch result |
| `profile` | M07 via M06 | profiler result |
| `optimize` | M03/M04 → M05/M06/M07 | optimization Patch / evidence |
| `verify` | M07 via readiness gate | verification result |
| `apply` | M09 approval → M05 apply/recovery | apply outcome |
| `history` | M09 query | ACL/redaction-filtered history |

`kh status`의 authorized output 최소 필드:

```text
repository_id
canonical_repository_root
branch
commit_sha
head_state
git_operation_state
working_tree_dirty
working_tree_diff_hash (display는 short/ref 가능)
graph_freshness
local_only_runtime_status
```

`kh history`는 current Repository ACL과 M08 protected-result policy를 다시 적용한 projection만 반환한다. Audit raw payload를 그대로 terminal에 dump하지 않는다.

---

## 11.5 Domain Model

### 11.5.1 Command Invocation

```python
@dataclass(frozen=True)
class CommandInvocation:
    request_id: CommandRequestId
    command: CliCommand
    cwd: Path
    repository_argument: Path | None
    target: str | None
    user_text: str | None
    patch_selector: PatchSelector | None
```

`user_text` / `target`은 in-memory untrusted input이다. 일반 Audit payload에 raw 원문을 자동 저장하지 않는다.

ACL 이후 downstream으로 전달하는 객체:

```python
@dataclass(frozen=True)
class AuthorizedCommandRequest:
    request_id: CommandRequestId
    command: CliCommand
    identity: IdentityContext
    repository: CanonicalRepositoryRef
    access: RepositoryAccessContext
    target: str | None
    user_text: str | None
    patch_selector: PatchSelector | None
```

`modify / optimize`의 natural-language request는 ACL 통과 후 M03 Trusted Request Intent Capture로 전달한다. M01이 임의로 `request_intent_id`를 생성하거나 user request를 축약/재작성해 authority로 만들지 않는다.

### 11.5.2 Identity

```python
class IdentitySource(Enum):
    KNOWLEDGE_HUB_SESSION = "knowledge_hub_session"
    LOCAL_OS_MAPPING = "local_os_mapping"


@dataclass(frozen=True)
class IdentityContext:
    user_id: UserId
    source: IdentitySource
    session_ref: str | None
    os_principal_ref: str | None
    authenticated_at: datetime
```

금지:

```text
raw JWT
raw refresh token
password
credential hash derived directly from bearer token
```

을 `IdentityContext`, Audit payload, normal log에 넣지 않는다. `session_ref`는 auth system이 제공한 non-secret opaque reference 또는 local credential handle이다.

### 11.5.3 Canonical Repository Reference

ACL 전에 확보 가능한 최소 identity:

```python
@dataclass(frozen=True)
class CanonicalRepositoryRef:
    repository_id: RepositoryId
    repository_root_id: RepositoryRootId
    canonical_repository_root: Path
    shared_git_identity_key: str
    filesystem_identity: str
    linked_worktree: bool
```

`canonical_repository_root`는 **현재 CLI invocation이 대상으로 삼은 physical worktree root**다. linked worktree마다 값은 다를 수 있다.

`shared_git_identity_key`는 사용자 입력 path hash가 아니다. persisted registration과 Safe Git이 확인한 Git common-dir / OS filesystem identity를 이용해 path alias와 linked worktree를 하나의 shared Repository identity에 연결한다.

Repository registration 시 `repository_id`는 trusted factory가 생성한 stable UUID이며 path alias에 따라 새 ID를 자동 생성하지 않는다. 동일 common Git repository의 linked worktree는 같은 `repository_id`를 사용하되 각각 별도 `repository_root_id / canonical_repository_root / filesystem_identity`를 갖는다.

### 11.5.4 Authorization

```python
@dataclass(frozen=True)
class RepositoryAccessContext:
    user_id: UserId
    repository_id: RepositoryId
    granted_permissions: frozenset[RepositoryPermission]
    authorization_decision_ref: str
    authorization_policy_version: str
    evaluated_at: datetime
```

이 객체는 과거 권한을 영구 보장하는 capability가 아니다. `apply / recovery / protected artifact read`처럼 요구사항이 current authorization 재검사를 요구하는 경로에서는 새 decision을 받아야 한다.

### 11.5.5 Approval Evidence

```python
@dataclass(frozen=True)
class ApprovalEvidenceView:
    approval_evidence_id: ApprovalEvidenceId

    request_intent_id: RequestIntentId
    protected_request_ref: str

    patch_id: PatchId
    revision: PatchRevision
    patch_hash: str
    final_diff_hash: str

    verification_result_id: VerificationResultId
    verification_basis_id: VerificationBasisId

    change_set_summary: ChangeSetSummary
    acceptance_mapping_summary: AcceptanceMappingSummary
    final_risk_summary: FinalRiskSummary
    verification_basis_summary: VerificationBasisSummary
    check_summary: tuple[VerificationCheckSummary, ...]
    exception_summary: tuple[SecurityExceptionSummary, ...]

    has_inconclusive: bool
    has_not_available: bool

    canonical_schema_version: str
    hash_algorithm: str
    evidence_hash: str
```

`evidence_hash`는 화면 문자열을 hash한 값이 아니라 authoritative structured fields의 versioned canonical serialization hash다. Terminal width / color / wrapping 변화가 Approval binding을 바꾸지 않는다. `hash_algorithm`은 공통 canonical hashing baseline에 따라 `SHA-256`을 사용한다.

`check_summary`는 required check만이 아니라 Approval 판단에 표시해야 하는 relevant check 상태를 포함한다. 따라서 required check가 모두 PASS/N/A라 `VERIFIED`인 경우에도 optional Evidence의 `INCONCLUSIVE / NOT_AVAILABLE` 존재 여부를 `has_inconclusive / has_not_available`로 명시적으로 표시할 수 있다. `verification_basis_summary`는 risk rule/threshold, required-check plan, Guardrail/Command/Sandbox/Security policy version reference를 사용자에게 inspection 가능한 범위로 제공한다.

---

## 11.6 Class / Interface Design

### 11.6.1 Identity

```python
class IdentityProvider(Protocol):
    def resolve(self, invocation: CommandInvocation) -> IdentityContext: ...


class CredentialStore(Protocol):
    def get_session_credential(self) -> CredentialHandle | None: ...


class IdentityVerifier(Protocol):
    def verify(self, credential: CredentialHandle) -> VerifiedIdentity: ...


class OsUserIdentityResolver(Protocol):
    def current_principal(self) -> OsPrincipal: ...
    def resolve_mapping(self, principal: OsPrincipal) -> IdentityContext | None: ...
```

Provider resolution:

```text
1. Knowledge Hub session credential이 존재함
   ├─ valid   → 해당 identity 사용
   └─ invalid / expired / unverifiable → IDENTITY_UNRESOLVED 또는 re-auth 요구
      (OS mapping으로 silent fallback 금지)

2. session credential 자체가 없음
   ├─ trusted Local OS User mapping이 명시적으로 enabled → OS identity mapping 시도
   └─ mapping 없음/실패 → IDENTITY_UNRESOLVED
```

OS mapping은 environment variable의 username 문자열을 신뢰하지 않는다. Linux는 effective UID / trusted OS account identity, Windows는 current access token SID 등 OS-authenticated principal을 사용한다. Mapping configuration은 Repository 밖 trusted local store에서 관리한다.

### 11.6.2 Repository Identity

```python
class MinimalRepositoryIdentityResolver(Protocol):
    def resolve(
        self,
        locator: RepositoryLocator,
    ) -> CanonicalRepositoryRef: ...


class RepositoryRegistrationStore(Protocol):
    def resolve_by_identity_key(
        self,
        identity_key: str,
    ) -> CanonicalRepositoryRef | None: ...

    def register(
        self,
        discovered: DiscoveredRepositoryIdentity,
    ) -> CanonicalRepositoryRef: ...
```

`MinimalRepositoryIdentityResolver`는 ACL 이전에 다음 최소 작업만 허용한다.

```text
input path canonicalization
Git repository 여부
worktree root / common Git repository identity 확인
path alias / linked worktree identity 확인
Local-Only boundary 판단에 필요한 object-source metadata 최소 확인
```

다음은 ACL 이후 `AuthorizedRepositoryContextLoader`가 수행한다.

```text
branch
commit SHA
history
working tree diff
source-derived metadata
Graph
source content
```

따라서 unauthorized user에게 branch name / commit history를 먼저 읽은 뒤 결과만 숨기는 구조를 금지한다.

### 11.6.3 Authorization

```python
class RepositoryAuthorizationService(Protocol):
    def authorize(
        self,
        user_id: UserId,
        repository_id: RepositoryId,
        required: frozenset[RepositoryPermission],
    ) -> AuthorizationDecision: ...
```

```python
@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    granted_permissions: frozenset[RepositoryPermission]
    decision_ref: str
    policy_version: str
    evaluated_at: datetime
    deny_reason_code: str | None
```

`deny_reason_code`는 UI/CLI에 raw internal policy expression이나 secret을 노출하지 않는다.

### 11.6.4 Command Gate

```python
class CommandSafetyGate(Protocol):
    def check(
        self,
        request: AuthorizedCommandRequest,
        context: AuthorizedRepositoryContext,
    ) -> CommandGateDecision: ...
```

M01 deterministic gate:

```text
MODIFY / OPTIMIZE / APPLY
→ head_state == NORMAL
→ destructive/in-progress Git operation 없음

MODIFY / OPTIMIZE
→ v1 dirty-tree policy에 따라 dirty이면 BLOCK

APPLY of newly VERIFIED revision
→ Approval/Apply 진입 시 clean-source policy를 요구

APPLY Recovery of already APPROVED revision
→ generic dirty-tree gate에서 선차단하지 않음
→ M05가 durable pre-apply / expected-post-apply hash와 현재 Repository state를 reconcile
→ unrelated dirty / partial / unknown이면 STALE_VERIFICATION 또는 remediation required

VERIFY
→ original Repository dirty 여부만으로 자동 차단하지 않음
→ exact Patch Verification readiness는 별도 gate로 판단
```

### 11.6.5 Verification Readiness

```python
class VerificationReadinessPort(Protocol):
    def resolve(
        self,
        repository_id: RepositoryId,
        selector: PatchSelector,
    ) -> VerificationReadiness: ...
```

필수 조건:

```text
lifecycle == APPLIED_TO_WORKTREE
Canonical Actual Change Set == COMPLETE
Post-Apply Diff Guardrail == ALLOW
Final Change Risk available
Verification Plan available
```

하나라도 없으면 M07 실행 요청을 만들지 않는다.

### 11.6.6 Approval / Apply

```python
class ApprovalEligibilityPort(Protocol):
    def evaluate(
        self,
        repository_id: RepositoryId,
        selector: PatchSelector,
    ) -> ApprovalEligibility: ...


class ApprovalEvidenceAssembler(Protocol):
    def assemble(
        self,
        eligibility: ApprovalEligibility,
        identity: IdentityContext,
        access: RepositoryAccessContext,
    ) -> ApprovalEvidenceView: ...


class ApprovalPrompt(Protocol):
    def confirm(self, evidence: ApprovalEvidenceView) -> bool: ...


class ApprovalPersistencePort(Protocol):
    def persist_approval(
        self,
        command_request_id: CommandRequestId,
        approver_user_id: UserId,
        authorization: AuthorizationDecision,
        evidence: ApprovalEvidenceView,
    ) -> ApprovalBindingId: ...


class ApplyEntryPort(Protocol):
    def apply_approved_revision(
        self,
        repository_id: RepositoryId,
        patch_id: PatchId,
        revision: PatchRevision,
        actor: UserId,
    ) -> ApplyOutcome: ...


class ApplyRecoveryPort(Protocol):
    def recover(
        self,
        repository_id: RepositoryId,
        patch_id: PatchId,
        revision: PatchRevision,
        actor: UserId,
    ) -> ApplyOutcome: ...
```

`ApprovalPersistencePort`는 M09 transaction boundary를 사용하며 exact evidence binding + `APPROVED` transition + required Audit를 crash-consistent하게 저장한다. M01이 DB row를 개별적으로 직접 update하지 않는다.

`ApprovalEvidenceAssembler`는 동일 `request_intent_id / patch_id / revision / verification_result_id / verification_basis_id`에 연결된 authoritative record만 join한다. stale cache나 다른 revision의 risk/check/exception summary를 섞지 않으며 binding inconsistency가 있으면 Evidence를 생성하지 않는다.

---

## 11.7 Repository Identity Resolution Algorithm

입력:

```text
cwd 또는 --repo PATH
```

알고리즘:

```text
1. 빈 path / NUL / platform-invalid path 거부
2. absolute path로 변환하되 user string을 authority로 사용하지 않음
3. OS physical path / file identity 확인
4. non-executing Safe Git discovery로 worktree root / common Git repository 확인
5. Git hook / filter / pager / credential helper / external command 실행 금지
6. implicit network fetch 금지
7. common Git directory의 OS filesystem identity로 `shared_git_identity_key` 구성
8. current worktree root의 `filesystem_identity` 구성
9. trusted RepositoryRegistrationStore에서 existing repository_id / root mapping 조회
10. path alias가 동일 filesystem identity를 가리키면 기존 repository_root_id 재사용
11. linked worktree면 shared repository_id + distinct repository_root_id 구성
12. 처음 보는 identity는 trusted local identity record를 bounded하게 생성할 수 있음
    (Repository ID 생성은 ACL grant가 아니며 source access를 허용하지 않음)
13. 해당 repository_id에 current ACL 적용
14. ACL ALLOW 후 branch / commit / dirty / source / graph context 로드
```

Linux identity evidence 후보:

```text
st_dev + st_ino of trusted Git common-dir
canonical common-dir path
worktree root file identity
```

Windows identity evidence 후보:

```text
VolumeSerialNumber + FileIdInfo
canonical handle-resolved path
```

단일 path 문자열이나 Repository remote URL을 stable identity authority로 사용하지 않는다. Git remote는 변경 가능하며 Repository identity가 아니다.

External alternates / promisor / shared object source가 identity/materialization 의미를 바꾸는 경우 M02/M08 policy result를 받아 authorized object source인지 확인한다. 이 단계에서 missing object를 자동 fetch하지 않는다.

---

## 11.8 DB / Persistence Ownership

M01은 별도의 독립 auth DB를 만들지 않는다.

권위 소유권:

| Data | Authority / persistence |
|---|---|
| user / session / role | existing Spring authentication / authorization authority |
| CLI credential secret | OS credential store; SQLite 저장 금지 |
| Local OS User mapping | Repository 밖 trusted local config/store |
| `repository_id` / canonical local identity mapping | M09 Local Store `repositories` domain |
| Repository ACL decision | current Spring authorization decision; M09에는 decision reference만 Audit |
| command/request Audit | M09 append-only Audit |
| Approval Evidence artifact/hash | M09 protected artifact/store |
| Approval Binding | M09 crash-consistent store |

M09의 `repositories` domain은 Repository identity와 root mapping을 분리한다. M01 관점의 required DDL shape는 다음과 같다. 최종 migration 파일은 M09 schema appendix가 authority다.

```sql
CREATE TABLE repositories (
    repository_id TEXT PRIMARY KEY,
    shared_git_identity_key TEXT NOT NULL UNIQUE,
    registered_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE repository_roots (
    repository_root_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    canonical_root_key TEXT NOT NULL UNIQUE,
    canonical_repository_root TEXT NOT NULL,
    filesystem_identity TEXT NOT NULL,
    root_kind TEXT NOT NULL CHECK (root_kind IN ('PRIMARY', 'LINKED_WORKTREE')),
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY (repository_id) REFERENCES repositories(repository_id),
    UNIQUE (repository_id, filesystem_identity)
);

CREATE INDEX idx_repository_roots_repository
    ON repository_roots(repository_id, active);
```

`canonical_root_key`는 OS/path semantics를 반영한 trusted canonical lookup key이며 display path 문자열 자체에 SQLite의 기본 text collation을 적용해 identity를 판단하지 않는다.

처음 보는 local Repository에 identity row를 만드는 것은 **authorization grant가 아니다**. identity record 생성 후에도 current Spring ACL/RBAC가 ALLOW하지 않으면 branch/source/graph를 읽지 않는다. identity record 생성은 bounded single-repository discovery만 수행하며 arbitrary recursive filesystem registration을 하지 않는다.

ACL rule 자체를 이 local table에 복제해 authoritative source로 사용하지 않는다.

---

## 11.9 State / Sequence — Read-only Command

`kh explain` 예:

```text
User
 │
 │ kh explain Foo
 ▼
CLI
 │ REQUEST_RECEIVED (raw source/prompt 제외)
 ▼
IdentityService
 │
 ├─ fail → IDENTITY_UNRESOLVED
 └─ success
      │ IDENTITY_RESOLVED
      ▼
MinimalRepositoryIdentityResolver
      │
      ├─ fail → NOT_A_GIT_REPOSITORY / identity error
      └─ canonical repository_id
             │
             ▼
RepositoryAuthorizationService(CODE_ANALYZE)
      │
      ├─ DENY → ACL_CHECKED(deny) → ACCESS_DENIED
      └─ ALLOW → ACL_CHECKED(allow)
                    │
                    ▼
AuthorizedRepositoryContextLoader
                    │
                    ▼
M02 → M03
```

`ACL_CHECKED` 이전에는 protected source / graph / history를 load하지 않는다.

---

## 11.10 State / Sequence — `kh verify`

```text
kh verify [selector]
  ↓
Identity + canonical repository identity
  ↓
current PATCH_VERIFY authorization
  ↓
PatchSelectorResolver
  ├─ 0 eligible → PATCH_NOT_READY_FOR_VERIFICATION
  ├─ >1 eligible and selector omitted → AMBIGUOUS_PATCH_SELECTION
  └─ exact revision
       ↓
VerificationReadinessPort
  ├─ Worktree not applied → BLOCK
  ├─ Change Set incomplete → CANONICAL_CHANGE_SET_UNAVAILABLE
  ├─ Post-Apply Guardrail != ALLOW → BLOCK
  ├─ Final Risk absent → BLOCK
  ├─ Verification Plan absent → BLOCK
  └─ READY
       ↓
M07 Verification entry
```

CLI가 `--force`, hidden flag, debug mode 등을 통해 readiness를 bypass하는 경로를 제공하지 않는다.

---

## 11.11 State / Sequence — `kh apply` Informed Approval

### VERIFIED revision

```text
1. Identity Resolve
2. Minimal Canonical Repository Identity Resolve
3. current PATCH_APPROVE + PATCH_APPLY authorization
4. exact Patch revision resolve
5. ApprovalEligibility evaluate
   - lifecycle == VERIFIED
   - canonical verified artifact durable
   - artifact hash/revision integrity valid
   - current verification basis compatible
   - apply-relevant security exception still eligible
6. ApprovalEvidenceView assemble from authoritative records
   - original request intent / protected request reference
   - Canonical Actual Change Set summary
   - Final Risk + rule/threshold refs
   - Verification checks + INCONCLUSIVE/NOT_AVAILABLE presence
   - Sensitive/Security/declassify/remote-publish relevance
   - Verification Basis / policy version refs
7. SafeTerminalRenderer renders exact structured evidence + protected detail inspection entry
8. User explicit confirmation
   ├─ decline → VERIFIED 유지 / ApprovalBinding 생성 없음 / Apply 호출 없음
   └─ confirm → continue
9. Confirmation 직후 current state 재조회
   - current authorization 재확인
   - patch/revision/hash/final_diff unchanged
   - verification_result_id/basis unchanged
   - protected request / acceptance mapping unchanged
   - security exception validity unchanged
   - evidence binding unchanged
10. exact canonical Approval Evidence artifact durable write
    ├─ fail → CRITICAL_PERSISTENCE_FAILED / VERIFIED 유지 / Apply 금지
    └─ durable → continue
11. M09 atomic transaction
   - USER_APPROVED audit
   - ApprovalBinding persist
   - APPROVED lifecycle transition
   - PATCH_STATE_CHANGED audit
    ├─ transaction fail → CRITICAL_PERSISTENCE_FAILED / VERIFIED 유지 / Apply 금지
    └─ durable commit → APPROVED
12. M05 ApplyEntryPort 호출
13. M05가 side effect 직전 current APPLY authorization / binding / source / policy를 다시 검사
```

8번 confirmation과 11번 persistence 사이에 authoritative state가 바뀌면 이전 화면에 대한 승인을 새 state에 재사용하지 않는다. `APPROVAL_REVALIDATION_REQUIRED`로 중단하고 새 Evidence를 다시 표시해야 한다.

Approval confirmation 자체는 raw Patch hash 문자열을 shell/input으로 재해석하지 않는 structured prompt다.

사용자가 exact canonical Patch / Change Set detail inspection을 선택하면 M09 protected artifact viewer port를 사용하고 **동일 repository current ACL + M08 sensitive/provenance policy를 다시 적용**한다. Detail viewer가 summary와 다른 revision/basis를 resolve하면 fail-closed하며 Approval을 계속하지 않는다.

### APPROVED revision / Recovery

동일 revision이 이미 `APPROVED`이고 `APPLIED`가 아닌 경우:

```text
kh apply
→ current PATCH_APPLY authorization
→ existing ApprovalBinding validity 확인
→ recovery binding exact-match 확인
   patch_id / revision / patch_hash / final_diff_hash /
   verification_result_id / verification_basis_id / approval_binding_id
→ 새 USER_APPROVED event 생성 금지
→ ApplyRecoveryPort
→ M05 lock 재획득 + pre/post-state recovery reconciliation
```

위 binding 중 하나라도 저장된 approved target과 다르면 Recovery로 진행하지 않는다. 기존 Approval을 다른 revision/result에 재사용하지 않는다.

기존 Approval binding만 무효이고 Verification이 여전히 valid한 경우:

```text
APPROVED → VERIFIED
→ re-approval required
```

Verification Basis까지 stale이면:

```text
→ STALE_VERIFICATION
```

일시적인 `APPLY_LOCK_UNAVAILABLE`은 `APPROVED`를 유지한다.

---

## 11.12 Security Boundary

### Credential

- raw JWT / password / refresh token을 log/Audit/exception에 넣지 않는다.
- credential은 OS credential store handle로 가져오며 Repository config나 environment variable이 credential path/provider를 임의 교체하지 못한다.
- auth failure message에는 token fragment를 포함하지 않는다.
- CLI child process / Sandbox로 auth credential을 상속하지 않는다.

### Terminal Rendering

모든 untrusted 문자열은 `SafeTerminalRenderer`를 통과한다.

```python
class SafeTerminalRenderer(Protocol):
    def text(self, value: str) -> SafeDisplayText: ...
    def table(self, rows: Sequence[SafeRow]) -> None: ...
```

필수 처리:

```text
ANSI / C0/C1 control sequence를 active terminal instruction으로 실행하지 않음
OSC 8 hyperlink escape 등 terminal escape 차단
Repository filename을 Rich/Markdown markup으로 해석하지 않음
newline/tab은 layout-safe representation으로 normalize 또는 escape
bidi control / zero-width control은 표시상 spoofing 가능성이 있으므로 visible escaping 또는 warning representation 적용
raw binary는 직접 terminal 출력하지 않음
```

Rich를 사용할 경우 untrusted 값은 `Text` object / `markup=False` equivalent로 전달하고 trusted layout markup과 데이터 문자열을 분리한다.

### Pre-ACL Disclosure

ACL 이전 허용 metadata는 canonical Repository identity를 확정하는 데 필요한 최소 filesystem/Git identity뿐이다. `branch / commit / history / source / graph / diff`는 기본적으로 current ACL 이후에만 읽는다.

---

## 11.13 Failure / Recovery / Exit Model

Domain error code는 module contract로 유지하고 CLI process exit code는 안정적인 category로 매핑한다.

| Exit | Category | 대표 domain errors |
|---:|---|---|
| `0` | success | 정상 완료 |
| `2` | CLI usage | invalid option / argument |
| `10` | identity | `IDENTITY_UNRESOLVED` |
| `11` | authorization | `ACCESS_DENIED`, `APPLY_AUTHORIZATION_DENIED`, `APPROVAL_AUTHORIZATION_REVOKED` |
| `12` | repository identity | `NOT_A_GIT_REPOSITORY` |
| `13` | repository state | `REPOSITORY_STATE_BLOCKED`, `DIRTY_WORKTREE_BLOCKED`, `WORKTREE_PREPARATION_BLOCKED`, `PROPOSAL_BASE_STALE` |
| `20` | patch selection/readiness | `AMBIGUOUS_PATCH_SELECTION`, `PATCH_NOT_READY_FOR_VERIFICATION`, `PATCH_NOT_VERIFIED`, `CANONICAL_CHANGE_SET_UNAVAILABLE` |
| `21` | verification/policy basis | `VERIFICATION_BASIS_MISMATCH`, `APPROVAL_REVALIDATION_REQUIRED` |
| `22` | artifact | `VERIFIED_ARTIFACT_UNAVAILABLE` |
| `23` | persistence | `CRITICAL_PERSISTENCE_FAILED` |
| `24` | temporary apply condition | `APPLY_LOCK_UNAVAILABLE` |
| `25` | stale/remediation | `STALE_VERIFICATION`, remediation-required condition |
| `70` | internal | unexpected trusted-agent failure |

Domain error의 상세 reason은 M09 Audit에 structured code/reference로 남기되 CLI에는 sensitive path/policy internals를 과도하게 노출하지 않는다.

Retry semantics:

```text
APPLY_LOCK_UNAVAILABLE
→ retryable, APPROVED 유지

CRITICAL_PERSISTENCE_FAILED
→ 자동 side effect retry 금지; durable store 정상성 확인 필요

STALE_VERIFICATION / remediation required
→ 자동 Apply retry 금지

ACCESS_DENIED / authorization revoked
→ 과거 Approval로 bypass 금지
```

---

## 11.14 Configuration / Policy

M01 trusted configuration 후보:

```yaml
cli:
  renderer:
    color: auto
    escape_untrusted: true

identity:
  providers:
    - knowledge_hub_session
    - local_os_mapping
  local_os_mapping_enabled: true

repository:
  identity_auto_create: true

approval:
  interactive_required: true
```

이 configuration은 Repository 내부 파일에서 authority-bearing 값으로 로드하지 않는다. Repository config가 `auto approval`, permission, identity provider, credential location을 self-authorize할 수 없다.

`repository.identity_auto_create`는 local Repository identity metadata 생성 여부만 제어한다. 기본 `true`는 현재 command가 지정한 단일 Git Repository에 대해 stable local `repository_id/root_id`를 만들 수 있다는 뜻이며, **ACL / source access / modification 권한을 자동 부여하지 않는다**. hardened deployment에서는 trusted admin registration만 허용하도록 `false`로 바꿀 수 있다.

---

## 11.15 API / IPC Contract

M01의 authorization authority가 Spring에 있는 경우 Python Agent는 raw credential을 임의 RPC payload에 반복 전달하지 않고 trusted local authentication bridge를 사용한다.

논리 contract:

```text
ResolveIdentity(credential_handle/session)
→ user_id + non-secret session_ref

AuthorizeRepository(user_id, repository_id, permissions[])
→ allowed + decision_ref + policy_version + evaluated_at
```

IPC가 localhost HTTP이면:

```text
loopback bind only
server authentication / local trust bootstrap 필요
request timeout
no redirect to external host
proxy environment 무시
```

Unix Domain Socket이면:

```text
owner/group permission 제한
socket path Repository 밖 trusted runtime directory
symlink-safe creation
peer credential 확인 가능 시 활용
```

exact endpoint / message schema는 `design/appendices/openapi.yaml` 또는 IPC schema에서 versioning한다.

---

## 11.16 Observability / Audit

M01에서 최소 연결하는 Audit:

```text
REQUEST_RECEIVED
IDENTITY_RESOLVED
ACL_CHECKED
APPLY_AUTHORIZATION_DENIED
APPROVAL_AUTHORIZATION_REVOKED
APPROVAL_REVALIDATION_REQUIRED
USER_APPROVED
APPROVAL_BINDING_RECORDED
CRITICAL_PERSISTENCE_FAILED
APPLY_LOCK_UNAVAILABLE
```

원칙:

- `REQUEST_RECEIVED`에 raw source / 전체 natural-language request / credential을 기본 저장하지 않는다.
- `IDENTITY_RESOLVED`는 `user_id / identity_source / session_ref` 수준으로 제한한다.
- `ACL_CHECKED`는 `repository_id / requested_permissions / decision_ref / policy_version / allow-deny`를 기록한다.
- user-visible terminal string 전체를 Audit에 복제하지 않는다.
- Approval은 exact `approval_evidence_hash/reference`를 binding한다.
- authorization recheck의 새 decision reference를 Apply/Recovery Audit과 연결한다.

---

## 11.17 Test Strategy

### Unit

```text
M01-UT-001 session identity success
M01-UT-002 invalid/expired session present → no OS fallback, re-auth/IDENTITY_UNRESOLVED
M01-UT-003 no session + enabled OS mapping failure → IDENTITY_UNRESOLVED
M01-UT-004 permission matrix per command
M01-UT-005 selector omitted + exactly one eligible revision
M01-UT-006 selector omitted + multiple revisions → AMBIGUOUS_PATCH_SELECTION
M01-UT-007 approval evidence canonical hash independent of terminal width/color
M01-UT-008 apply confirmation 후 state change → APPROVAL_REVALIDATION_REQUIRED
M01-UT-009 user declines approval → VERIFIED 유지 / no binding / no apply
M01-UT-010 APPROVED recovery does not create new approval event
```

### Repository identity / authorization integration

```text
M01-IT-001 symlink alias → same repository_id
M01-IT-002 relative/absolute aliases → same repository_id
M01-IT-003 linked worktrees → shared repository_id + distinct worktree root
M01-IT-004 different clones → distinct local repository_id
M01-IT-005 unauthorized caller → source/branch/history loader not invoked
M01-IT-006 detached HEAD read-only allowed with state displayed
M01-IT-007 detached HEAD MODIFY blocked
M01-IT-008 merge/rebase in-progress MODIFY/OPTIMIZE/APPLY blocked
M01-IT-009 dirty tree MODIFY/OPTIMIZE + newly-VERIFIED APPLY blocked
M01-IT-010 APPROVED Recovery with expected post-apply state is not preempted by generic dirty gate
M01-IT-011 missing Git object does not trigger network fetch
```

### Verification / approval

```text
M01-IT-012 verify before Worktree apply → blocked
M01-IT-013 incomplete Canonical Change Set → blocked
M01-IT-014 Post-Apply Guardrail blocked → verify entry not called
M01-IT-015 FAILED/INCONCLUSIVE/STALE cannot approve
M01-IT-016 VERIFIED artifact missing → approval blocked
M01-IT-017 Verification Basis incompatible → approval blocked/revalidation
M01-IT-018 approval persistence failure → VERIFIED 유지 + Apply not called
M01-IT-019 permission revoked after approval → Apply blocked
M01-IT-020 APPLY_LOCK_UNAVAILABLE → APPROVED 유지
M01-IT-021 APPROVED recovery exact binding → no duplicate USER_APPROVED
M01-IT-022 approval display includes protected request ref / policy basis / INCONCLUSIVE-NOT_AVAILABLE flags
```

### CLI security

```text
M01-SEC-001 filename with ANSI escape cannot alter terminal
M01-SEC-002 OSC hyperlink payload rendered inert
M01-SEC-003 Rich/Markdown-like filename rendered as text
M01-SEC-004 bidi-control filename visibly escaped/warned
M01-SEC-005 auth token absent from logs/audit on success/failure
M01-SEC-006 Repository config cannot select auth provider or grant permission
M01-SEC-007 unauthorized repo does not leak branch/commit/history
M01-SEC-008 environment username spoof cannot impersonate OS mapping
```

M11 E2E acceptance에서는 위 integration test를 실제 M02/M05/M07/M09 구현과 다시 연결한다.

---

## 11.18 Requirement Traceability

| Requirement | Detailed Design |
|---|---|
| M01-FR-01 CLI commands | 11.4 |
| M01-FR-02 CLI-first / safe display | 11.1, 11.12 |
| M01-FR-03 Repository auto-detection / canonical identity | 11.5.3, 11.6.2, 11.7 |
| M01-FR-04 Identity Establishment | 11.5.2, 11.6.1 |
| M01-FR-05 ACL before protected analysis | 11.6.2~11.6.3, 11.9, 11.12 |
| M01-FR-06 verify gate | 11.6.5, 11.10 |
| M01-FR-06 informed approval | 11.5.5, 11.6.6, 11.11 |
| M01-FR-06 current authorization recheck | 11.5.4, 11.11 |
| M01-FR-06 Apply Recovery | 11.11, 11.13 |
| M01 errors / block conditions | 11.13 |
| M01 success criteria | 11.7~11.17 |

---

## 11.19 Implementation Order

```text
M01-01  core typed IDs / enums / domain errors 보강
M01-02  SafeTerminalRenderer
M01-03  IdentityProvider + CredentialStore ports
M01-04  Session identity adapter / OS mapping adapter
M01-05  MinimalRepositoryIdentityResolver port + repository identity/root persistence
M01-06  RepositoryAuthorizationService adapter
M01-07  PermissionMatrix + CommandSafetyGate
M01-08  PatchSelectorResolver + VerificationReadiness integration
M01-09  ApprovalEvidenceAssembler + canonical evidence hash
M01-10  ApprovalCoordinator + M09 atomic persistence integration
M01-11  ApplyEntry / Recovery integration
M01-12  Typer command wiring
M01-13  unit / integration / security test suite
```

M01-05의 Safe Git discovery 실제 구현은 M02/M05 Safe Git 상세설계와 공유한다. M01에서 임시로 일반 `git` subprocess를 별도 구현하지 않는다.

---

# 12. M02 — Repository Context / Code Graph Detailed Design

## 12.1 Design Goals

M02는 현재 Repository의 **실제 source state와 분석 가능한 경계**를 authoritative Evidence로 정의하고, 그 기준점에 연결된 Code Graph를 제공한다.

핵심 목표:

```text
1. current source state를 commit SHA 하나로 축약하지 않는다.
2. staged / unstaged / relevant untracked source를 포함한 Source Snapshot을 만든다.
3. Repository root 밖 symlink / untrusted mount / nested repository / unauthorized object source를 자동 신뢰하지 않는다.
4. Git inspection은 repository-controlled executable integration을 실행하지 않는 Safe Git profile만 사용한다.
5. Graph는 정확한 source snapshot / ingestion policy / builder version에 binding한다.
6. Graph freshness는 commit뿐 아니라 source snapshot / dirty state / policy / coverage를 비교해 판정한다.
7. Potpie는 local-only secondary structural evidence로만 사용한다.
8. M02 자체가 mutation / network fetch / Repository code execution authority를 갖지 않는다.
```

M02의 authority 범위:

```text
authoritative
├── canonical Repository Context
├── Source Snapshot identity
├── source / filesystem / nested-repository boundary evidence
├── Git object/materialization state evidence
└── Graph snapshot ↔ source snapshot binding

non-authoritative / secondary
├── Potpie interpretation
├── LLM explanation
└── Graph에서 유도한 자연어 role description
```

M02는 Patch 생성 / Worktree mutation / Sandbox execution을 수행하지 않는다. Runtime이 필요한 extractor / LSP / build-aware analyzer는 M06 경계로 넘긴다.

---

## 12.2 Component Architecture

```text
AuthorizedRepositoryHandle
          │
          ▼
RepositoryContextService
          │
          ├── SafeGitRepositoryInspector
          │     ├── HEAD / branch / operation state
          │     ├── staged / unstaged Git state
          │     └── object / sparse / gitlink metadata
          │
          ├── RepositoryBoundaryDetector
          │     ├── nested .git boundary
          │     ├── symlink / junction boundary
          │     ├── mount / reparse boundary
          │     └── submodule gitlink boundary
          │
          ├── SourceEnumerator
          │     └── ingestion-policy bounded filesystem walk
          │
          ├── SecureSourceReader
          │     └── M08 classification before source consumption
          │
          └── SourceSnapshotter
                ├── canonical SourceManifest
                ├── working_tree_* hash
                └── SourceSnapshotReference

SourceSnapshotReference
          │
          ▼
StructuralLanguageRegistry
          │
          ├── PythonStructuralAdapter
          ├── ECMAScriptStructuralAdapter      # planned
          └── JavaStructuralAdapter            # planned
          │
          ▼
Normalized Structural Evidence
          │
          ▼
GraphCoordinator
          │
          ├── StaticGraphProvider
          ├── PotpieGraphProvider
          ├── ChangedSourceDetector
          ├── ChangedSymbolDetector
          ├── GraphSnapshotPublisher
          └── GraphFreshnessEvaluator

          ▼
M09 Repository / Graph Evidence Store
```

M02 내부에서 path를 처리할 때 raw user path를 authority로 사용하지 않는다. M01이 확정한 `repository_id / repository_root_id / canonical_repository_root`를 입력으로 받으며, source entry는 모두 canonical root에 상대적인 path identity로 표현한다.

---

## 12.3 Package / Directory Layout

```text
code-agent/
└── repository/
    ├── domain/
    │   ├── context.py
    │   ├── snapshot.py
    │   ├── source_entry.py
    │   ├── boundary.py
    │   ├── git_state.py
    │   ├── graph.py
    │   └── errors.py
    │
    ├── application/
    │   ├── context_service.py
    │   ├── source_snapshot_service.py
    │   ├── graph_service.py
    │   ├── graph_freshness.py
    │   └── incremental_refresh.py
    │
    ├── ports/
    │   ├── git_inspector.py
    │   ├── source_reader.py
    │   ├── boundary_detector.py
    │   ├── graph_provider.py
    │   └── repository_store.py
    │
    ├── adapters/
    │   ├── git/
    │   │   ├── safe_git_inspector.py
    │   │   ├── nul_parser.py
    │   │   └── object_state.py
    │   ├── filesystem/
    │   │   ├── linux_source_reader.py
    │   │   ├── windows_source_reader.py
    │   │   └── boundary_probe.py
    │   ├── static_analysis/
    │   │   ├── parser_registry.py
    │   │   └── static_graph_provider.py
    │   └── potpie/
    │       ├── local_client.py
    │       └── potpie_graph_provider.py
    │
    └── persistence/
        ├── sqlite_repository_store.py
        └── manifest_artifact_store.py

code-agent/
└── languages/
    ├── domain.py
    ├── registry.py
    ├── ports/
    │   ├── structural.py
    │   └── toolchain.py
    ├── python/
    │   ├── structural.py
    │   └── capabilities.py
    ├── ecmascript/
    │   ├── structural.py
    │   └── capabilities.py
    └── java/
        ├── structural.py
        └── capabilities.py
```

현재 `analysis/python_graph.py` 구현은 폐기하지 않고 `PythonStructuralAdapter`가 감싸는 첫 implementation으로 사용한 뒤 점진적으로 adapter package로 이동한다. 새 추상화를 도입한다는 이유로 이미 검증된 Python AST 로직을 즉시 재작성하지 않는다.

M01의 Repository discovery와 M05의 Safe Git Worktree 준비는 별도 `git` wrapper를 만들지 않고 공통 Safe Git primitives를 재사용한다. 단, M02는 inspection-only method만 소비한다.

---

## 12.4 Domain Model

### 12.4.1 RepositoryContext

```python
@dataclass(frozen=True)
class RepositoryContext:
    context_id: RepositoryContextId

    repository_id: RepositoryId
    repository_root_id: RepositoryRootId
    canonical_repository_root: Path

    branch: str | None
    commit_sha: str | None
    head_state: HeadState
    git_operation_state: GitOperationState

    base_commit: str | None

    working_tree_dirty: bool
    working_tree_diff_hash: str
    staged_diff_hash: str
    unstaged_diff_hash: str
    working_tree_source_snapshot_hash: str

    source_snapshot_id: SourceSnapshotId

    git_object_state: GitObjectMaterializationState
    nested_repository_boundaries: tuple[NestedRepositoryBoundary, ...]
    filesystem_boundaries: tuple[FilesystemBoundaryEvidence, ...]

    detected_languages: tuple[DetectedLanguage, ...]
    ingestion_policy_version: str
    snapshot_schema_version: str

    source_completeness: SourceCompleteness
    created_at: datetime
```

`canonical_repository_root`는 local runtime에서만 사용되는 path이며 일반 Audit/Web payload에 무조건 노출하지 않는다. 외부 조회 계약은 기본적으로 `repository_id / repository_root_id`를 사용한다.

### 12.4.2 HeadState

```python
class HeadState(StrEnum):
    NORMAL = "NORMAL"
    DETACHED = "DETACHED"
    UNBORN = "UNBORN"
    UNRESOLVED = "UNRESOLVED"
```

`UNRESOLVED`는 repository metadata 손상, required local object 부재 또는 Safe Git inspection 실패로 HEAD 의미를 확정할 수 없는 경우 사용한다.

`UNBORN`은 `HEAD`가 유효한 `refs/heads/<branch>`를 가리키지만 해당 branch ref가 아직 존재하지 않고 첫 commit 이전이라는 사실을 safe metadata/object Evidence로 확인한 경우다. 단순 ref 누락을 모두 `UNBORN`으로 추정하지 않는다. 현재 저장소 구현의 `MetadataInspector`는 이 상태를 아직 `UNRESOLVED`와 구분하지 못하므로 **known implementation gap**으로 기록하고, `M02-CTX-003`을 충족하기 전 mutation readiness를 부여하지 않는다.

### 12.4.3 GitOperationState

```python
class GitOperationKind(StrEnum):
    NONE = "NONE"
    MERGE = "MERGE"
    REBASE = "REBASE"
    CHERRY_PICK = "CHERRY_PICK"
    REVERT = "REVERT"
    BISECT = "BISECT"
    SEQUENCER = "SEQUENCER"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class GitOperationState:
    kind: GitOperationKind
    in_progress: bool
    evidence_codes: tuple[str, ...]
```

M02는 operation state를 판정하지만 mutation 허용 여부는 M01/M05 command gate가 결정한다.

### 12.4.4 GitObjectMaterializationState

```python
@dataclass(frozen=True)
class GitObjectMaterializationState:
    sparse_checkout_enabled: bool
    sparse_scope_ref: ArtifactRef | None

    partial_clone_enabled: bool
    promisor_configured: bool

    alternates_present: bool
    alternates: tuple[GitObjectSourceRef, ...]

    replace_refs_present: bool
    replace_ref_count: int

    lfs_detected: bool
    missing_required_objects: tuple[str, ...]

    object_source_authorization: ObjectSourceAuthorization
    completeness: SourceCompleteness
```

`missing_required_objects`는 object id 또는 non-secret identifier 중심으로 기록한다. Missing object 때문에 network fetch가 필요하더라도 M02가 자동 fetch하지 않는다.

### 12.4.5 SourceCompleteness

```python
class SourceCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
```

의미:

```text
COMPLETE
  현재 ingestion policy가 정의한 scope 내 source를 모두 안전하게 식별/읽을 수 있음

PARTIAL
  sparse materialization, missing object, unsupported parser/source type,
  unreadable source 등으로 scope 일부가 분석되지 못함

BLOCKED
  unauthorized object source, unsafe filesystem boundary,
  Local-Only violation 등으로 분석을 시작/계속할 수 없음
```

Sensitive File이 policy에 의해 의도적으로 제외된 것은 그 자체로 `PARTIAL`이 아니다. Snapshot scope에 `POLICY_EXCLUDED`로 기록하고, **정의된 ingestion scope 안에서 완전한지**를 기준으로 completeness를 판단한다.

---

## 12.5 Source Entry / Snapshot Model

### 12.5.1 SourceEntry

```python
@dataclass(frozen=True)
class SourceEntry:
    relative_path: RepoRelativePath
    path_identity: PathIdentity

    entry_type: SourceEntryType
    mode: int | None
    size_bytes: int | None

    content_hash: str | None
    link_target_hash: str | None

    git_tracking_state: GitTrackingState
    classification: DataClassification
    inclusion: SourceInclusion

    language: str | None
    filesystem_identity: FilesystemIdentity | None
```

```python
class SourceEntryType(StrEnum):
    REGULAR_FILE = "REGULAR_FILE"
    SYMLINK = "SYMLINK"
    GITLINK = "GITLINK"
    DIRECTORY = "DIRECTORY"
    UNSUPPORTED_SPECIAL = "UNSUPPORTED_SPECIAL"
```

`content_hash`는 policy상 source content를 읽을 수 있는 regular source에 대해서만 계산한다. Sensitive excluded content를 hash하기 위해 raw content를 일반 source pipeline으로 읽지 않는다.

### 12.5.2 SourceInclusion

```python
class SourceInclusion(StrEnum):
    INCLUDED = "INCLUDED"
    POLICY_EXCLUDED = "POLICY_EXCLUDED"
    NESTED_REPOSITORY_EXCLUDED = "NESTED_REPOSITORY_EXCLUDED"
    FILESYSTEM_BOUNDARY_EXCLUDED = "FILESYSTEM_BOUNDARY_EXCLUDED"
    UNSUPPORTED_EXCLUDED = "UNSUPPORTED_EXCLUDED"
```

각 exclusion에는 별도 reason/evidence가 연결된다.

### 12.5.3 SourceSnapshotReference

```python
@dataclass(frozen=True)
class SourceSnapshotReference:
    source_snapshot_id: SourceSnapshotId

    repository_id: RepositoryId
    repository_root_id: RepositoryRootId

    base_commit: str | None

    working_tree_dirty: bool
    working_tree_diff_hash: str
    staged_diff_hash: str
    unstaged_diff_hash: str

    source_snapshot_hash: str

    snapshot_schema_version: str
    ingestion_policy_version: str
    path_identity_version: str
    hash_algorithm: str

    source_scope_hash: str
    manifest_artifact_ref: ArtifactRef

    entry_count: int
    included_bytes: int
    completeness: SourceCompleteness
```

`working_tree_source_snapshot_hash`는 `SourceSnapshotReference.source_snapshot_hash`를 사용한다.

---

## 12.6 Source Enumeration Boundary

### 12.6.1 원칙

Source set은 `git diff`, `git ls-files`, `.gitignore` 중 하나만으로 만들지 않는다.

```text
Safe Git metadata
+
policy-bounded filesystem traversal
+
M08 sensitive classification
+
Repository / filesystem boundary detection
→ SourceManifest
```

이유:

```text
- relevant untracked source가 Git diff에 없음
- ignored source도 분석 대상일 수 있음
- .gitignore는 security boundary가 아님
- nested Repository는 parent working tree 아래 존재할 수 있음
- sparse checkout은 filesystem materialization과 전체 tracked set이 다름
```

### 12.6.2 SourceEnumerator

```python
class SourceEnumerator(Protocol):
    def enumerate(
        self,
        repo: AuthorizedRepositoryHandle,
        policy: IngestionPolicy,
    ) -> Iterator[SourceEntryCandidate]: ...
```

Enumerator는 다음을 기본 제외한다.

```text
.git directory/file administrative content
registered Knowledge Hub temp/worktree/output roots
untrusted nested repository content
untrusted mount/reparse boundary
policy excluded build/cache/vendor directory
unsupported special filesystem object
```

`node_modules`, `.venv`, `target`, `build`, `dist` 등은 성능상 default exclusion 후보지만 **hard-coded security authority가 아니라 versioned ingestion policy**로 관리한다.

### 12.6.3 Traversal Limits

```text
max_files
max_total_source_bytes
max_single_file_bytes
max_directory_depth
max_path_bytes
max_symlink_hops_when_explicitly_resolving
snapshot_timeout
```

Limit 초과 시 전체 source를 분석했다고 주장하지 않는다. Policy에 정의된 scope 자체가 quota를 넘으면 `PARTIAL` 또는 `BLOCKED` decision을 명시적으로 반환한다.

---

## 12.7 Filesystem Boundary Detection

### 12.7.1 RepositoryBoundaryDetector

```python
class RepositoryBoundaryDetector(Protocol):
    def inspect_entry(
        self,
        repo: AuthorizedRepositoryHandle,
        candidate: SourceEntryCandidate,
    ) -> BoundaryDecision: ...
```

검사 대상:

```text
symlink
junction / reparse point
mount point / bind mount
nested .git directory/file
submodule working tree
special filesystem object
```

### 12.7.2 Symlink

기본 source traversal은 symlink를 directory처럼 따라가지 않는다.

Symlink 자체는 다음 metadata로 표현할 수 있다.

```text
relative link path
link target text hash
link target classification
resolved target scope = INSIDE_REPOSITORY | OUTSIDE_REPOSITORY | UNRESOLVED
```

Target content 분석이 필요한 경우:

```text
readlink without follow
→ target resolution
→ canonical root containment check
→ nested repository / mount boundary check
→ M08 sensitive classification
→ explicit source-read policy
→ content read
```

Repository root 밖 target은 읽지 않는다.

### 12.7.3 Mount / Reparse Boundary

Linux는 가능한 경우 root와 entry의 mount identity를 비교한다.

후보 evidence:

```text
statx mount id
st_dev
/proc/self/mountinfo trusted parse
```

Windows는 volume identity / reparse tag / final handle path를 사용한다.

Repository 내부 path라도 별도 mount/volume/reparse boundary에 들어가면 parent Repository source로 자동 traversal하지 않는다. Trusted boundary mapping이 없으면 `FILESYSTEM_BOUNDARY_EXCLUDED`로 처리한다.

### 12.7.4 Hardlink

M02 read-only ingestion은 path가 canonical Repository root 안에 있다고 해서 hardlink origin을 증명했다고 주장하지 않는다.

방어:

```text
- filesystem identity를 Evidence로 기록할 수 있음
- high-confidence secret/content classification을 M08에서 적용
- mutation authority를 부여하지 않음
- protected inode alias 여부가 명시적으로 탐지되면 source ingestion을 BLOCK
```

Hardlink-safe mutation은 M05 `SecureFilesystem` 책임이다.

---

## 12.8 Nested Repository / Submodule Boundary

### 12.8.1 NestedRepositoryBoundary

```python
@dataclass(frozen=True)
class NestedRepositoryBoundary:
    relative_path: RepoRelativePath
    kind: NestedRepositoryKind

    candidate_repository_root: Path | None
    candidate_repository_id: RepositoryId | None

    parent_gitlink: bool
    authorized: bool

    decision: BoundaryDecisionCode
```

```python
class NestedRepositoryKind(StrEnum):
    NESTED_DOT_GIT_DIR = "NESTED_DOT_GIT_DIR"
    NESTED_DOT_GIT_FILE = "NESTED_DOT_GIT_FILE"
    LINKED_WORKTREE = "LINKED_WORKTREE"
    SUBMODULE_WORKTREE = "SUBMODULE_WORKTREE"
```

### 12.8.2 정책

```text
parent Repository ACL
≠
nested Repository ACL
```

Nested repository candidate가 발견되면:

```text
1. parent traversal 중단
2. boundary evidence 기록
3. 등록된 repository_id mapping 확인
4. nested Repository를 분석하려면 M01 authorization service를 통해 별도 ACL 확인
5. authorized인 경우에도 parent SourceSnapshot/Graph에 합치지 않고 별도 RepositoryContext로 분석
```

Submodule의 `160000` gitlink entry는 parent Repository의 structural metadata로 포함할 수 있다. Submodule working tree source는 별도 Repository authorization 없이는 읽지 않으며, authorization이 있더라도 parent graph에 병합하지 않는다.

---

## 12.9 Safe Git Inspection Profile

M02는 공통 `SafeGitExecutionProfile`의 inspection-only subset을 사용한다.

### 12.9.1 Interface

```python
class GitRepositoryInspector(Protocol):
    def inspect_head(self, repo: AuthorizedRepositoryHandle) -> HeadInfo: ...
    def inspect_operation_state(self, repo: AuthorizedRepositoryHandle) -> GitOperationState: ...
    def inspect_worktree_state(self, repo: AuthorizedRepositoryHandle) -> GitWorktreeState: ...
    def inspect_index(self, repo: AuthorizedRepositoryHandle) -> GitIndexState: ...
    def inspect_object_state(self, repo: AuthorizedRepositoryHandle) -> GitObjectMaterializationState: ...
    def inspect_gitlinks(self, repo: AuthorizedRepositoryHandle) -> tuple[GitlinkEntry, ...]: ...
```

M02 adapter에는 `checkout`, `reset`, `clean`, `apply`, `fetch`, `submodule update`, `lfs pull` method를 제공하지 않는다.

### 12.9.2 Process Environment

최소 원칙:

```text
shell = false
argv array only
stdin = closed unless explicitly needed
GIT_TERMINAL_PROMPT=0
GIT_OPTIONAL_LOCKS=0
GIT_CONFIG_NOSYSTEM=1
HOME=<isolated-empty-home>
GIT_CONFIG_GLOBAL=<trusted-empty-config>
GIT_PAGER=cat
PAGER=cat
GIT_EDITOR=true
GIT_SEQUENCE_EDITOR=true
```

명시적으로 무력화/고정할 설정 후보:

```text
core.hooksPath
core.fsmonitor
diff.external
pager.*
credential.helper
filter.*.process
filter.*.clean
filter.*.smudge
core.attributesFile
```

Diff/introspection command는 지원되는 경우 `--no-ext-diff`, `--no-textconv`, `-z` / machine-readable output을 사용한다.

Repository local config를 단순 신뢰하지 않고, inspection command가 executable integration을 호출할 수 있는 config key는 trusted override로 차단한다.

### 12.9.3 Safe Git Command / Status Synthesis

구현 시 exact command는 adapter conformance test로 고정한다. 기본 후보:

```text
git rev-parse / symbolic-ref 계열 HEAD inspection
git diff --cached --raw -z --no-ext-diff --no-textconv
git ls-files -z --stage
git check-attr -z --stdin <required attrs>   # attribute metadata only
```

`git status` / worktree diff처럼 worktree content를 Git이 변환·비교하는 command는 clean/smudge/process filter, fsmonitor 등 repository-controlled executable integration을 호출하지 않는 것이 adapter test로 입증된 profile에서만 사용한다.

v1 기본은 필요 시 다음처럼 status를 합성한다.

```text
HEAD/index state from non-executing Git plumbing
+ index entries
+ direct filesystem enumeration/stat/hash
+ trusted built-in EOL/attribute handling 가능한 범위
→ staged / unstaged / relevant-untracked state
```

외부 filter가 필요한 path의 exact Git-clean comparison을 executable filter 실행 없이 재현할 수 없으면 해당 path를 보수적으로 `COMPARISON_UNCERTAIN`으로 표시하고 mutation-safe cleanliness를 주장하지 않는다. Read-only current-source snapshot은 raw filesystem source를 기준으로 계속 식별할 수 있다.

사람용 porcelain text를 line split하여 filename을 복원하지 않는다.

### 12.9.4 No Implicit Network

M02 inspection 경로에는 다음이 존재하지 않는다.

```text
fetch
pull
submodule update --init
lfs pull
missing object auto-fetch
promisor fetch
credential prompt
```

Partial clone에서 local object가 없어 분석을 완료할 수 없으면 `PARTIAL/BLOCKED` evidence를 반환한다.

---

## 12.10 Git Object Source Authorization

### 12.10.1 검사 대상

```text
.git/objects/info/alternates
GIT_ALTERNATE_OBJECT_DIRECTORIES 영향
shared object directory
replace refs
partial clone / promisor settings
LFS pointer / materialization state
sparse checkout / skip-worktree
```

Caller-provided Git environment의 `GIT_DIR`, `GIT_WORK_TREE`, `GIT_OBJECT_DIRECTORY`, alternates는 Safe Git profile에서 제거하거나 trusted 값으로 재구성한다.

### 12.10.2 ObjectSourceAuthorization

```python
class ObjectSourceAuthorization(StrEnum):
    LOCAL_REPOSITORY = "LOCAL_REPOSITORY"
    TRUSTED_LOCAL_SHARED_STORE = "TRUSTED_LOCAL_SHARED_STORE"
    AUTHORIZED_INTERNAL_STORE = "AUTHORIZED_INTERNAL_STORE"
    UNAUTHORIZED_EXTERNAL_STORE = "UNAUTHORIZED_EXTERNAL_STORE"
    UNKNOWN = "UNKNOWN"
```

External object source가 Repository content authority에 영향을 주는데 authorization을 확인할 수 없으면 Graph/Source complete analysis를 fail-closed한다.

Replace ref가 존재하면 실제 object identity 의미가 달라질 수 있으므로 presence 자체를 Repository Context에 기록한다. v1에서는 trusted policy가 명시적으로 허용하지 않은 replace-ref 사용을 mutation 계열의 safe base로 사용하지 않는다.

---

## 12.11 Dirty Working Tree / Diff Identity

### 12.11.1 Dirty 판정

```text
tracked staged change
OR tracked unstaged change
OR ingestion policy 범위의 relevant untracked source
→ working_tree_dirty = true
```

Git status에 untracked file이 존재하더라도 ingestion policy에서 명확히 non-source output으로 제외된 경우 source snapshot dirty 의미와 Git working tree dirty 의미를 구분할 필요가 있다.

따라서 내부적으로 두 값을 유지한다.

```python
@dataclass(frozen=True)
class GitWorktreeState:
    git_dirty: bool
    analysis_source_dirty: bool
    staged_records: tuple[GitChangeRecord, ...]
    unstaged_records: tuple[GitChangeRecord, ...]
    relevant_untracked: tuple[RepoRelativePath, ...]
```

외부 `RepositoryContext.working_tree_dirty`는 mutation gate 요구사항 때문에 **Git repository mutation-safety 관점의 dirty**를 사용한다. `analysis_source_dirty`는 Graph freshness / source snapshot 판단에 추가 사용한다.

### 12.11.2 Diff Hash

Raw textual diff 자체를 hash authority로 사용하지 않는다.

Canonical `GitChangeRecord` 후보:

```text
path identity
change kind
old mode / new mode
HEAD object id if available
index object id if available
worktree content hash if policy-readable
rename/copy source path identity if available
```

```text
staged_diff_hash
  = H(canonical staged GitChangeRecord set)

unstaged_diff_hash
  = H(canonical unstaged GitChangeRecord set)

working_tree_diff_hash
  = H(staged + unstaged + relevant untracked change identity)
```

Clean sentinel:

```text
CLEAN:<diff-schema-version>
```

Hash에는 `diff_schema_version / path_identity_version / hash_algorithm`을 integrity metadata로 연결한다.

---

## 12.12 Source Snapshot Algorithm

```text
INPUT
  AuthorizedRepositoryHandle
  IngestionPolicy

1. Safe Git HEAD / index / worktree / object state inspect
2. filesystem root identity capture
3. policy-bounded source traversal
4. nested Repository / mount / symlink boundary classify
5. candidate path M08 classification
6. INCLUDED regular source를 secure read
7. relevant untracked source merge
8. deterministic SourceManifest 생성
9. staged / unstaged / working-tree diff identities 계산
10. source scope / completeness 확정
11. manifest canonical serialization
12. source_snapshot_hash 계산
13. manifest artifact durable write
14. M09 metadata transaction
15. SourceSnapshotReference publish
```

Step 13~14 중 persistence가 실패하면 해당 snapshot reference를 authoritative durable Evidence로 publish하지 않는다. Read-only command가 ephemeral snapshot으로 계속 동작할 수 있는지는 caller policy가 결정하되, Audit/재현성을 요구하는 결과는 durable reference 없이 완료 상태로 기록하지 않는다.

---

## 12.13 Canonical Source Manifest

Canonical entry 최소 필드:

```text
relative_path_identity
entry_type
mode
size
content_hash-or-link-target-hash
tracking_state
classification_label
inclusion_decision
```

Deterministic rule:

```text
1. OS raw path identity 보존
2. display path와 identity path 분리
3. platform-specific comparison key 별도 생성
4. canonical byte ordering
5. duplicate/alias identity 발견 시 fail-closed 또는 explicit collision evidence
6. schema version을 hash 의미와 연결
```

Linux filename identity를 임의 Unicode normalization하여 동일 파일명으로 합치지 않는다.

Manifest에는 raw source body를 저장하지 않는다. Source body 보존이 별도로 필요하면 일반 snapshot manifest가 아니라 protected artifact policy를 사용한다.

---

## 12.14 Source Read / Sensitive Classification Order

민감 content는 **LLM/Graph parser에 넣은 뒤 masking**하지 않는다.

```text
Path candidate
→ path-based classification
→ secure read eligibility
→ bounded content probe / secret scanner where policy permits
→ final classification
→ INCLUDED / POLICY_EXCLUDED
→ parser / graph input
```

High-confidence secret scanner가 source entry를 Sensitive로 승격하면 일반 Graph ingestion에서 제외한다.

Sensitive content를 Graph/ingestion context에 포함하려면 M08의 scoped `read-context` decision이 해당 user / repository / path 범위에서 유효해야 하며, downstream graph/result에 `sensitive_provenance`를 전달한다. 단순 `modify` 또는 `runtime-read` exception으로 Graph ingestion을 허용하지 않는다.

---

## 12.15 Language Detection / Support Registry

Language detection은 다음 Evidence를 조합한다.

```text
file extension / filename
trusted structural adapter capability
project metadata (read-only)
source shebang (bounded read가 허용된 경우)
```

Repository-controlled build command를 실행하여 언어를 탐지하지 않는다. `package.json`, `tsconfig.json`, `pom.xml`, `build.gradle` 같은 metadata는 detection/capability 후보 Evidence일 뿐, command/network/security authority가 아니다.

언어 family mapping:

```text
.py / .pyi                           → PYTHON
.ts / .tsx / .mts / .cts            → TYPESCRIPT
.js / .jsx / .mjs / .cjs            → JAVASCRIPT
.java                                → JAVA
```

TypeScript/JavaScript는 실행 도구 관점에서 `ECMAScript` family로 묶을 수 있지만 source identity에는 원래 `LanguageId`를 유지한다.

```python
@dataclass(frozen=True)
class DetectedLanguage:
    language: LanguageId
    family: LanguageFamily
    file_count: int
    source_bytes: int
    confidence: float
    structural_status: LanguageSupportStatus
    toolchain_status: LanguageSupportStatus
    effective_status: LanguageSupportStatus
    capabilities: frozenset[LanguageCapability]
    structural_adapter_id: str | None
    structural_adapter_version: str | None
    toolchain_adapter_id: str | None
    toolchain_adapter_version: str | None
    evidence_codes: tuple[str, ...]
```

Unknown file은 억지로 특정 language로 매핑하지 않는다. Adapter가 없는 언어도 SourceSnapshot에는 포함될 수 있으나 structural graph coverage는 `PARTIAL`로 계산한다.

### 12.15.1 StructuralLanguageRegistry

```python
class StructuralLanguageRegistry(Protocol):
    def resolve(
        self,
        language: LanguageId,
    ) -> StructuralLanguageAdapter | None: ...

    def structural_capabilities(
        self,
        language: LanguageId,
    ) -> frozenset[LanguageCapability]: ...
```

M02에는 이 structural-only port만 주입한다. M02 code path에서는 `LanguageToolchainAdapter`, command template registry, executable path를 resolve할 수 없다.

Registry 자체가 trusted configuration이다. Repository source가 임의 adapter/plugin path를 등록하거나 새로운 structural/executable capability를 self-authorize할 수 없다.

### 12.15.2 Multi-language Repository

Repository는 하나의 primary language만 가진다고 가정하지 않는다.

```text
Spring + Next.js + Python repository
→ JAVA + TYPESCRIPT/JAVASCRIPT + PYTHON을 동시에 탐지
→ language별 structural result 생성
→ normalized graph에 병합
→ cross-language relation은 명시 Evidence가 있을 때만 연결
```

REST endpoint ↔ frontend call, JNI, subprocess, generated client와 같은 cross-language relation은 단순 이름 유사성만으로 authoritative edge를 만들지 않는다. OpenAPI/schema/import/config 또는 runtime Evidence가 존재할 때 `DEPENDS_ON/CROSSES_EXTERNAL_BOUNDARY` 등으로 연결하고 provenance를 보존한다.

---

## 12.16 Graph Domain Model

### 12.16.1 GraphSnapshotReference

```python
@dataclass(frozen=True)
class GraphDataRef:
    store_kind: str              # ARTIFACT | LOCAL_GRAPH_DB | POTPIE_LOCAL 등
    opaque_ref: str
    content_hash: str
    schema_version: str


@dataclass(frozen=True)
class GraphSnapshotReference:
    graph_snapshot_id: GraphSnapshotId

    repository_id: RepositoryId
    source_snapshot_id: SourceSnapshotId

    graph_base_commit: str | None
    graph_source_snapshot_hash: str
    graph_working_tree_diff_hash: str

    graph_snapshot_schema_version: str
    graph_ingestion_policy_version: str
    graph_builder_version: str
    language_adapter_set_hash: str

    graph_data_ref: GraphDataRef
    graph_artifact_ref: ArtifactRef | None
    provider_refs: tuple[GraphProviderRunRef, ...]

    covered_source_scope_hash: str
    covered_entry_count: int
    completeness: GraphCompleteness

    created_at: datetime
```

`graph_data_ref`는 restart 이후에도 동일 Graph를 조회할 수 있는 durable local reference다. 구현에 따라 M09-managed graph artifact, local graph database snapshot, Potpie/local provider snapshot id 등이 될 수 있지만 current ACL 밖 remote reference는 허용하지 않는다. `GraphCompleteness.COMPLETE`를 publish하려면 해당 reference의 durability/integrity가 확인되어야 한다.

### 12.16.2 GraphCompleteness

```python
class GraphCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
```

### 12.16.3 Node / Edge

```python
@dataclass(frozen=True)
class GraphNode:
    node_id: GraphNodeId
    symbol_key: str
    kind: GraphNodeKind
    relative_path: RepoRelativePath
    qualified_name: str | None
    language: str | None
    span: SourceSpan | None
    evidence_refs: tuple[EvidenceRef, ...]

@dataclass(frozen=True)
class GraphEdge:
    edge_id: GraphEdgeId
    source_node_id: GraphNodeId
    target_node_id: GraphNodeId
    kind: GraphEdgeKind
    confidence: float
    evidence_refs: tuple[EvidenceRef, ...]
```

Node kind 후보:

```text
FILE
MODULE
CLASS
INTERFACE
FUNCTION
METHOD
VARIABLE
CONFIG
TEST
EXTERNAL_SYSTEM
```

Edge kind 후보:

```text
DEFINES
IMPORTS
CALLS
CALLED_BY      # query projection으로 계산 가능; 저장은 CALLS 하나만 둘 수 있음
REFERENCES
EXTENDS
IMPLEMENTS
DEPENDS_ON
TESTS
CONFIGURES
CROSSES_EXTERNAL_BOUNDARY
```

`called_by`처럼 역관계는 canonical edge를 중복 저장하지 않고 query projection으로 계산할 수 있다.

---

## 12.17 Language / Graph Provider Interfaces

M02의 language-specific 로직은 **non-executing structural adapter**로 제한한다.

```python
class StructuralLanguageAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    languages: frozenset[LanguageId]

    def parse_file(
        self,
        source: SecureSourceView,
    ) -> StructuralFileEvidence: ...

    def build_relations(
        self,
        files: tuple[StructuralFileEvidence, ...],
        metadata: TrustedProjectMetadataView,
    ) -> LanguageGraphResult: ...

    def resolve_symbol(
        self,
        query: SymbolQuery,
        graph: LanguageGraphResult,
    ) -> SymbolResolutionResult: ...
```

이 interface 구현은 Repository code, package script, compiler plugin, annotation processor, build hook을 실행하지 않는다. 그런 semantic/runtime 분석이 필요한 경우 M06/M07의 `LanguageToolchainAdapter` 경계로 넘긴다.

현재/계획 adapter:

```text
PythonStructuralAdapter
→ 현재 `analysis/python_graph.py` stdlib AST 기반 implementation 재사용
→ import / class / function / call-expression structural evidence

ECMAScriptStructuralAdapter (planned)
→ TS/JS/TSX/JSX/MJS/CJS
→ non-executing trusted parser(Tree-sitter 계열 우선)로 syntax/import/export/symbol evidence
→ tsserver/TypeScript semantic resolution은 Host M02가 아니라 sandbox-backed toolchain 경로

JavaStructuralAdapter (planned)
→ .java syntax/import/type/method evidence
→ non-executing trusted parser(Tree-sitter 계열 우선)
→ JDT LS / annotation-processing-aware semantic resolution은 sandbox-backed toolchain 경로
```

Graph provider는 language adapter 결과를 normalized graph로 합성한다.

```python
class CodeGraphProvider(Protocol):
    provider_id: str
    provider_version: str

    def build(
        self,
        snapshot: SourceSnapshotReference,
        manifest: SourceManifestView,
        languages: tuple[DetectedLanguage, ...],
    ) -> GraphBuildResult: ...

    def refresh(
        self,
        previous: GraphSnapshotReference,
        current: SourceSnapshotReference,
        changes: ChangedSourceSet,
    ) -> GraphBuildResult: ...
```

Provider는 source body가 필요할 때 `SecureSourceReader`를 통해서만 읽는다. Arbitrary path open을 허용하지 않는다.

Repository code / plugin / project command를 실행할 가능성이 있는 provider는 Host-side structural implementation으로 등록하지 않고 M06 sandbox-backed provider/toolchain 경로로 분리한다.

---

## 12.18 Static Graph Provider

v1 primary structural graph는 non-executing parser 기반을 권장한다.

```text
Source Snapshot
→ language parser registry
→ syntax / import / symbol extraction
→ source-backed graph
```

원칙:

```text
- parser input size/time bound
- malformed source fail-safe
- parser crash 격리
- dynamic call을 사실로 단정하지 않음
- unresolved relation은 unresolved/low-confidence로 표현
- generated/project plugin 실행 없음
```

Static parser가 호출관계를 확정할 수 없는 언어/패턴에서는 LLM 추측으로 `CALLS` authoritative edge를 만들지 않는다.

Language-specific raw AST를 그대로 공통 graph contract로 노출하지 않고 다음 normalized relation으로 변환한다.

```text
FILE / MODULE / CLASS / INTERFACE / FUNCTION / METHOD / TEST
DEFINES / IMPORTS / REFERENCES / EXTENDS / IMPLEMENTS / CALLS / TESTS
```

언어 adapter capability가 없는 source entry는 silently drop하지 않는다. `unsupported_entry_count / unsupported_language_set`을 Graph coverage에 기록하여 `COMPLETE` 오판을 막는다.

---

## 12.19 Potpie Adapter

### 12.19.1 Authority

```text
Current Source
>
Static Analysis / LSP
>
Current Potpie Graph
>
LLM Recommendation
```

Potpie edge가 current source/parser evidence와 충돌하면 current source 쪽을 우선하고 conflict evidence를 남길 수 있다.

### 12.19.2 Local-Only Runtime Attestation

Potpie client 생성 전 M08 `RuntimeSecurityVerifier`에서 최소 다음을 확인한다.

```text
Potpie runtime classification = LOCAL
Code Graph storage = LOCAL
Embedding = LOCAL
LLM provider = LOCAL
Telemetry = DISABLED
External source transmission = DISABLED
Internet egress = BLOCKED
```

Local의 구체 endpoint 형태는 배포 방식에 따라 Unix socket / loopback / trusted local container network가 될 수 있다. URL 문자열만으로 Local-Only를 판정하지 않고 runtime attestation + network policy를 사용한다.

판정은 원인을 구분한다.

```text
Potpie process/service 단순 UNAVAILABLE
→ Potpie secondary provider 사용 불가
→ static/source 기반 read-only 분석은 가능하되 Potpie coverage 부재를 표시

External provider / external embedding / telemetry enabled / external source transmission / egress policy violation
→ Local-Only security violation
→ Code Intelligence 전체 실행 BLOCK
```

보안 위반을 provider fallback으로 숨기지 않는다.

### 12.19.3 Potpie Input

Potpie에 넘기는 source set도 M02 SourceSnapshot의 INCLUDED set과 동일한 Sensitive/Nested/Filesystem boundary를 적용한다. Potpie 자체 crawler가 canonical Repository root를 별도로 재탐색하도록 맡기지 않는다.

---

## 12.20 Graph Build Coordinator

```python
class GraphCoordinator:
    def build_current_graph(
        self,
        repository: AuthorizedRepositoryHandle,
    ) -> GraphSnapshotReference: ...

    def refresh_current_graph(
        self,
        repository: AuthorizedRepositoryHandle,
    ) -> GraphSnapshotReference: ...
```

Sequence:

```text
Current Repository Context
→ exact SourceSnapshotReference
→ Local-Only attestation
→ primary Static Graph build
→ optional Potpie secondary evidence
→ provider result merge
→ coverage/completeness calculate
→ durable local graph data persist + integrity confirm
→ optional graph artifact persist
→ graph metadata transaction
→ GraphSnapshotReference publish
```

Graph metadata를 먼저 `COMPLETE`로 저장하고 실제 provider/artifact persistence가 나중에 실패하는 순서를 허용하지 않는다.

---

## 12.21 Graph Freshness

### 12.21.1 GraphFreshness

```python
class GraphFreshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
```

### 12.21.2 Evaluator

```python
class GraphFreshnessEvaluator:
    def evaluate(
        self,
        current: SourceSnapshotReference,
        graph: GraphSnapshotReference | None,
        current_policy: GraphPolicyContext,
    ) -> GraphFreshnessResult: ...
```

`FRESH` 조건은 최소 다음이 모두 일치해야 한다.

```text
graph exists
AND graph completeness == COMPLETE
AND current Source completeness == COMPLETE
AND graph_base_commit == current.base_commit
AND graph_source_snapshot_hash == current.source_snapshot_hash
AND graph_working_tree_diff_hash == current.working_tree_diff_hash
AND graph_ingestion_policy_version == current ingestion policy version
AND graph schema semantics compatible
AND graph builder semantics compatible
AND graph language_adapter_set_hash == current trusted structural adapter set hash
AND covered_source_scope_hash == current.source_scope_hash
```

`branch` 자체는 graph content identity의 필수 비교키로 두지 않는다. 서로 다른 branch가 **동일 commit + 동일 exact source snapshot + 동일 policy**를 가리키면 graph content를 재사용할 수 있다. 단, 분석 결과의 Repository Context에는 현재 branch를 별도로 binding한다.

### 12.21.3 STALE vs PARTIAL

```text
STALE
  graph가 과거의 complete snapshot을 정확히 나타내지만 current snapshot과 다름

PARTIAL
  current source 또는 graph coverage 자체가 incomplete하거나
  parser/provider 일부가 실패하여 complete relation set을 주장할 수 없음

UNAVAILABLE
  graph 없음 / provider 전체 실패 / graph artifact unusable
```

현재 commit이 같아도 source snapshot 또는 working-tree diff가 다르면 `FRESH`가 아니다.

---

## 12.22 Incremental Update

### 12.22.1 ChangedSourceDetector

```python
class ChangedSourceDetector:
    def compare(
        self,
        old: SourceManifestView,
        new: SourceManifestView,
    ) -> ChangedSourceSet: ...
```

비교 대상:

```text
added
modified
deleted
renamed-if-provable
mode/type changed
symlink target changed
gitlink changed
classification/inclusion changed
```

Incremental change detection은 Git diff만 사용하지 않고 old/new Source Manifest를 비교한다. 따라서 relevant untracked source와 policy-driven inclusion change도 감지한다.

### 12.22.2 ChangedSymbolDetector

```python
class ChangedSymbolDetector(Protocol):
    def detect(
        self,
        previous_graph: GraphSnapshotReference,
        current_graph_candidate: GraphBuildResult,
        changed_sources: ChangedSourceSet,
    ) -> ChangedSymbolSet: ...
```

Symbol rename은 증명 가능한 parser evidence가 없으면 delete+add로 처리한다.

### 12.22.3 Full Rebuild 조건

다음은 incremental refresh 대신 full rebuild 후보다.

```text
ingestion policy semantics changed
snapshot schema/path identity semantics changed
graph builder major semantics changed
structural language adapter/version/capability set changed
large change threshold 초과
nested repository boundary changed
source completeness PARTIAL → COMPLETE 또는 COMPLETE → PARTIAL
parser/provider state corruption
incremental provider가 delete/rename/type change를 안전하게 처리하지 못함
```

Incremental optimization 때문에 freshness correctness를 낮추지 않는다.

---

## 12.23 File / Function Query Contract

### File relation

```python
@dataclass(frozen=True)
class FileRelationView:
    file: FileNodeView
    imports: tuple[FileNodeRef, ...]
    imported_by: tuple[FileNodeRef, ...]
    dependencies: tuple[DependencyRef, ...]
    related_configs: tuple[FileNodeRef, ...]
    related_tests: tuple[FileNodeRef, ...]
```

### Symbol relation

```python
@dataclass(frozen=True)
class SymbolRelationView:
    symbol: SymbolNodeView
    calls: tuple[SymbolRef, ...]
    called_by: tuple[SymbolRef, ...]
    inputs: tuple[SymbolInput, ...]
    outputs: tuple[SymbolOutput, ...]
    exceptions: tuple[ExceptionEvidence, ...]
    side_effects: tuple[SideEffectEvidence, ...]
    shared_dependencies: tuple[DependencyRef, ...]
    external_boundaries: tuple[ExternalBoundaryRef, ...]
```

`input/output/exception/side effect`는 parser/source evidence가 없으면 `UNKNOWN`으로 유지하며 LLM natural-language 추론을 structural fact field에 저장하지 않는다.

---

## 12.24 Evidence Priority / Conflict Model

```python
class EvidenceAuthority(IntEnum):
    CURRENT_SOURCE = 400
    STATIC_ANALYSIS = 300
    CURRENT_POTPIE_GRAPH = 200
    LLM_RECOMMENDATION = 100
```

Runtime/performance fact는 M07 Evidence가 더 높은 authority를 가진다.

Conflict result 예:

```python
@dataclass(frozen=True)
class EvidenceConflict:
    subject_ref: EvidenceSubjectRef
    higher_authority_ref: EvidenceRef
    lower_authority_ref: EvidenceRef
    resolution: str
```

낮은 authority를 삭제할 필요는 없지만 최종 fact resolution에서 우선순위를 명확히 한다.

---

## 12.25 Persistence / DB Schema

M02는 full source body를 일반 DB에 저장하지 않는다.

### 12.25.1 `repository_context_snapshots`

```sql
CREATE TABLE repository_context_snapshots (
    context_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    repository_root_id TEXT NOT NULL,

    branch TEXT,
    commit_sha TEXT,
    head_state TEXT NOT NULL,
    git_operation_state TEXT NOT NULL,

    base_commit TEXT,

    working_tree_dirty INTEGER NOT NULL,
    working_tree_diff_hash TEXT NOT NULL,
    staged_diff_hash TEXT NOT NULL,
    unstaged_diff_hash TEXT NOT NULL,
    working_tree_source_snapshot_hash TEXT NOT NULL,

    source_snapshot_id TEXT NOT NULL,
    source_completeness TEXT NOT NULL,

    git_object_state_json TEXT NOT NULL,
    ingestion_policy_version TEXT NOT NULL,
    snapshot_schema_version TEXT NOT NULL,

    created_at TEXT NOT NULL,

    FOREIGN KEY (repository_id) REFERENCES repositories(repository_id),
    FOREIGN KEY (repository_root_id) REFERENCES repository_roots(repository_root_id)
);
```

`git_object_state_json`에는 secret/raw config를 저장하지 않고 normalized evidence만 저장한다.

### 12.25.2 `source_snapshots`

```sql
CREATE TABLE source_snapshots (
    source_snapshot_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    repository_root_id TEXT NOT NULL,

    base_commit TEXT,

    working_tree_dirty INTEGER NOT NULL,
    working_tree_diff_hash TEXT NOT NULL,
    staged_diff_hash TEXT NOT NULL,
    unstaged_diff_hash TEXT NOT NULL,

    source_snapshot_hash TEXT NOT NULL,
    source_scope_hash TEXT NOT NULL,

    snapshot_schema_version TEXT NOT NULL,
    ingestion_policy_version TEXT NOT NULL,
    path_identity_version TEXT NOT NULL,
    hash_algorithm TEXT NOT NULL,

    manifest_artifact_id TEXT NOT NULL,
    entry_count INTEGER NOT NULL,
    included_bytes INTEGER NOT NULL,
    completeness TEXT NOT NULL,

    created_at TEXT NOT NULL,

    FOREIGN KEY (manifest_artifact_id) REFERENCES artifacts(artifact_id)
);
```

Manifest artifact에는 path/hash/classification metadata가 포함될 수 있으므로 Repository ACL과 artifact classification을 적용한다.

### 12.25.3 `graph_snapshots`

```sql
CREATE TABLE graph_snapshots (
    graph_snapshot_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,

    graph_base_commit TEXT,
    graph_source_snapshot_hash TEXT NOT NULL,
    graph_working_tree_diff_hash TEXT NOT NULL,

    graph_snapshot_schema_version TEXT NOT NULL,
    graph_ingestion_policy_version TEXT NOT NULL,
    graph_builder_version TEXT NOT NULL,
    language_adapter_set_hash TEXT NOT NULL,

    covered_source_scope_hash TEXT NOT NULL,
    covered_entry_count INTEGER NOT NULL,
    completeness TEXT NOT NULL,

    graph_data_ref TEXT NOT NULL,
    graph_artifact_id TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (source_snapshot_id) REFERENCES source_snapshots(source_snapshot_id),
    FOREIGN KEY (graph_artifact_id) REFERENCES artifacts(artifact_id)
);
```

### 12.25.4 `graph_provider_runs`

```sql
CREATE TABLE graph_provider_runs (
    graph_provider_run_id TEXT PRIMARY KEY,
    graph_snapshot_id TEXT NOT NULL,

    provider_id TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    runtime_classification TEXT NOT NULL,
    result_state TEXT NOT NULL,

    covered_entry_count INTEGER NOT NULL,
    failure_summary TEXT,

    started_at TEXT NOT NULL,
    finished_at TEXT,

    FOREIGN KEY (graph_snapshot_id) REFERENCES graph_snapshots(graph_snapshot_id)
);
```

Provider raw logs는 일반 row에 넣지 않고 M06/M09 output policy를 따른다.

### 12.25.5 Boundary Evidence

Boundary detail은 row explosion을 피하기 위해 canonical protected artifact로 저장하고 DB에는 summary/reference를 둘 수 있다.

```text
boundary_evidence_artifact_id
nested_repository_count
filesystem_boundary_count
excluded_entry_count
```

Web/CLI는 current ACL을 통과한 경우에만 detail을 resolve한다.

---

## 12.26 Store Interface

```python
class RepositoryEvidenceStore(Protocol):
    def persist_source_snapshot(
        self,
        snapshot: PendingSourceSnapshot,
    ) -> SourceSnapshotReference: ...

    def persist_repository_context(
        self,
        context: PendingRepositoryContext,
    ) -> RepositoryContext: ...

    def persist_graph_snapshot(
        self,
        graph: PendingGraphSnapshot,
    ) -> GraphSnapshotReference: ...

    def latest_graph_for_repository(
        self,
        repository_id: RepositoryId,
    ) -> GraphSnapshotReference | None: ...
```

Store가 durable metadata를 반환하기 전까지 caller는 `SourceSnapshotReference` / `GraphSnapshotReference`를 durable authority로 취급하지 않는다.

---

## 12.27 M01/M02 Authorization Contract

M02 public application service는 raw path만 받아 source를 읽지 않는다.

```python
@dataclass(frozen=True)
class AuthorizedRepositoryHandle:
    repository_id: RepositoryId
    repository_root_id: RepositoryRootId
    canonical_repository_root: Path

    user_id: UserId
    authorization_decision_ref: str
    authorization_policy_version: str
    authorization_evaluated_at: datetime
    granted_permissions: frozenset[RepositoryPermission]
```

필수 permission 예:

```text
REPOSITORY_STATUS
CODE_ANALYZE
GRAPH_READ
GRAPH_BUILD
```

`GRAPH_READ`는 저장된 graph 조회, `GRAPH_BUILD`는 current source를 읽어 graph를 생성하는 작업으로 분리할 수 있다.

M02는 handle에 포함된 decision을 신뢰하는 것만으로 장기 capability를 만들지 않는다. 장시간 build 또는 sensitive exception 사용 시 policy가 요구하면 current authorization을 재확인한다.

---

## 12.28 API / IPC Contract

내부 Agent API 후보:

```text
GetRepositoryContext(repository_id, repository_root_id)
BuildSourceSnapshot(repository_id, repository_root_id)
GetGraphFreshness(repository_id)
BuildGraph(repository_id, source_snapshot_id)
RefreshGraph(repository_id)
GetFileRelations(repository_id, graph_snapshot_id, file_ref)
GetSymbolRelations(repository_id, graph_snapshot_id, symbol_ref)
```

응답은 항상 다음 basis를 포함한다.

```text
repository_id
repository_root_id
source_snapshot_id
source_snapshot_hash
graph_snapshot_id if applicable
graph_freshness
graph/source completeness
policy/schema version
```

Caller가 graph snapshot id를 생략한 경우에도 서버가 선택한 exact snapshot id를 응답에 명시한다. stale graph를 current graph처럼 조용히 반환하지 않는다.

---

## 12.29 Sequence — `kh status`

```text
M01 AuthorizedRepositoryHandle
→ M02 RepositoryContextService
→ Safe Git HEAD/operation/object inspect
→ boundary-aware Source Snapshot
→ latest GraphSnapshot lookup
→ GraphFreshnessEvaluator
→ M08 runtime security status reference
→ RepositoryStatusView
```

`kh status`에서 Graph build를 자동 강제하지 않는다. 현재 graph가 stale이면 `STALE`을 보여주고 explicit/defined refresh policy에 따라 별도 refresh할 수 있다.

---

## 12.30 Sequence — Dirty `kh explain`

```text
M01 CODE_ANALYZE authorized
→ current SourceSnapshot 생성
   ├─ staged 포함
   ├─ unstaged 포함
   └─ relevant untracked 포함
→ existing graph freshness
   ├─ FRESH → 사용
   ├─ STALE → incremental refresh / source cross-check
   ├─ PARTIAL → source evidence 우선 + limitation 표시
   └─ UNAVAILABLE → source/static only 가능
→ M03 explain
```

READ-ONLY static explain은 dirty source를 허용하므로 답변 basis에 dirty/source snapshot hash를 반드시 연결한다.

---

## 12.31 Sequence — Runtime Request Gate Support

M02는 runtime 실행 자체를 하지 않고 M03/M06가 판단할 수 있는 source-state evidence를 제공한다.

```text
PROFILE / PERFORMANCE
→ RepositoryContext.working_tree_dirty
   ├─ false → runtime pipeline 가능
   └─ true
       ├─ dirty snapshot reproduction capability = verified → explicit snapshot path
       └─ unsupported → DIRTY_WORKTREE_BLOCKED
```

v1 기본은 dirty runtime reproduction을 지원하지 않으므로 dirty runtime은 차단한다.

---

## 12.32 Failure / Error Model

```python
class RepositoryErrorCode(StrEnum):
    REPOSITORY_CONTEXT_UNAVAILABLE = "REPOSITORY_CONTEXT_UNAVAILABLE"
    SAFE_GIT_POLICY_BLOCKED = "SAFE_GIT_POLICY_BLOCKED"
    GIT_OBJECT_SOURCE_UNAUTHORIZED = "GIT_OBJECT_SOURCE_UNAUTHORIZED"
    GIT_OBJECT_MISSING = "GIT_OBJECT_MISSING"

    SOURCE_SNAPSHOT_PARTIAL = "SOURCE_SNAPSHOT_PARTIAL"
    SOURCE_SNAPSHOT_BLOCKED = "SOURCE_SNAPSHOT_BLOCKED"
    SOURCE_TRAVERSAL_LIMIT_EXCEEDED = "SOURCE_TRAVERSAL_LIMIT_EXCEEDED"
    SOURCE_READ_FAILED = "SOURCE_READ_FAILED"
    SOURCE_PATH_COLLISION = "SOURCE_PATH_COLLISION"

    NESTED_REPOSITORY_UNAUTHORIZED = "NESTED_REPOSITORY_UNAUTHORIZED"
    FILESYSTEM_BOUNDARY_BLOCKED = "FILESYSTEM_BOUNDARY_BLOCKED"

    GRAPH_UNAVAILABLE = "GRAPH_UNAVAILABLE"
    GRAPH_PARTIAL = "GRAPH_PARTIAL"
    GRAPH_POLICY_MISMATCH = "GRAPH_POLICY_MISMATCH"
    GRAPH_PROVIDER_FAILED = "GRAPH_PROVIDER_FAILED"

    POTPIE_LOCAL_ONLY_VIOLATION = "POTPIE_LOCAL_ONLY_VIOLATION"
```

`PARTIAL`은 항상 fatal exception일 필요는 없다. EXPLAIN처럼 source fallback이 가능한 read-only task는 limitation을 표시하고 진행할 수 있다. MODIFY/OPTIMIZE 등의 mutation authority에는 caller policy가 stricter gate를 적용한다.

---

## 12.33 Configuration / Policy

M02 config는 Repository source 안의 config로 authority를 확대하지 않는다.

Trusted config 후보:

```yaml
repository_analysis:
  snapshot_schema_version: source-snapshot-v1
  diff_schema_version: working-diff-v1
  path_identity_version: path-id-v1
  hash_algorithm: sha256

  traversal:
    max_files: 200000
    max_total_source_bytes: 2147483648
    max_single_file_bytes: 20971520
    max_directory_depth: 128
    timeout_seconds: 120

  graph:
    snapshot_schema_version: graph-v1
    builder_version: static-graph-v1
    incremental_change_ratio_limit: 0.20

  potpie:
    enabled: true
    require_local_attestation: true
```

위 숫자는 initial defaults 후보이며 운영 환경에서 versioned trusted policy로 조정 가능하다. Requirement semantics가 아니라 implementation configuration이다.

Repository 내부 config는 language/project metadata hint를 제공할 수 있지만 sensitive exclusion, object source trust, network, nested-repository ACL, Local-Only policy를 완화하지 못한다.

---

## 12.34 Observability / Audit

주요 Audit:

```text
REPOSITORY_CONTEXT_CAPTURED
SOURCE_SNAPSHOT_CREATED
GRAPH_REFRESHED
SAFE_GIT_POLICY_BLOCKED
NESTED_REPOSITORY_BOUNDARY_DETECTED
FILESYSTEM_BOUNDARY_DETECTED
OBJECT_SOURCE_POLICY_BLOCKED
GRAPH_PROVIDER_PARTIAL
POTPIE_LOCAL_ONLY_VIOLATION
```

기존 M09 event vocabulary와 충돌하지 않도록 실제 event enum은 M09에서 최종 통합한다. 여기서 새 event를 반드시 제품 요구사항으로 추가하는 것은 아니며, detail은 existing generic analysis/security event payload로 표현할 수 있다.

Audit payload 기본 포함:

```text
repository_id
repository_root_id
source_snapshot_id/hash
graph_snapshot_id if applicable
completeness/freshness
policy/schema/builder version
boundary counts
block/partial reason code
```

금지:

```text
raw source body
sensitive file content
credential-bearing Git config
raw external object-store credential
```

---

## 12.35 Test Strategy

### 12.35.1 Repository Context

```text
M02-CTX-001 clean normal repository
M02-CTX-002 detached HEAD
M02-CTX-003 unborn HEAD
M02-CTX-004 merge in progress
M02-CTX-005 rebase in progress
M02-CTX-006 cherry-pick/revert/sequencer state
M02-CTX-007 safe inspector failure → UNRESOLVED/BLOCK
```

### 12.35.2 Dirty / Snapshot

```text
M02-SNP-001 staged tracked change reflected
M02-SNP-002 unstaged tracked change reflected
M02-SNP-003 relevant untracked source reflected
M02-SNP-004 ignored-but-policy-relevant source reflected
M02-SNP-005 excluded build artifact does not alter source scope unexpectedly
M02-SNP-006 same source → deterministic snapshot hash
M02-SNP-007 different content same commit → different snapshot hash
M02-SNP-008 path identity collision → fail-closed
M02-SNP-009 traversal quota exceeded → PARTIAL/BLOCKED
M02-SNP-010 snapshot manifest contains no source body
```

### 12.35.3 Boundary Security

```text
M02-BND-001 symlink outside repo not followed
M02-BND-002 symlink inside repo reclassified before read
M02-BND-003 nested .git directory excluded
M02-BND-004 nested .git file / linked-worktree boundary excluded
M02-BND-005 unauthorized submodule working tree excluded
M02-BND-006 parent gitlink metadata retained
M02-BND-007 bind mount / mount-id boundary excluded
M02-BND-008 Windows reparse/junction boundary excluded
M02-BND-009 .git administrative metadata never ingested
M02-BND-010 sensitive symlink target cannot bypass M08
```

### 12.35.4 Git Object State

```text
M02-GIT-001 alternates trusted local store
M02-GIT-002 unauthorized alternates → block
M02-GIT-003 caller GIT_ALTERNATE_OBJECT_DIRECTORIES ignored/sanitized
M02-GIT-004 partial clone missing object does not fetch
M02-GIT-005 promisor config recorded
M02-GIT-006 replace ref detected
M02-GIT-007 sparse checkout scope recorded
M02-GIT-008 Safe Git does not invoke external diff/textconv
M02-GIT-009 Safe Git does not invoke credential helper/prompt
M02-GIT-010 repository clean/smudge/process filter is not executed during status synthesis
M02-GIT-011 filter-dependent comparison uncertainty cannot be reported as clean
```

### 12.35.5 Graph Freshness

```text
M02-GRF-001 exact source/policy/builder match → FRESH
M02-GRF-002 same commit + dirty content change → STALE
M02-GRF-003 same diff hash semantics but different source snapshot → not FRESH
M02-GRF-004 ingestion policy changed → not FRESH
M02-GRF-005 graph incomplete → PARTIAL
M02-GRF-006 sparse source incomplete → PARTIAL
M02-GRF-007 no graph → UNAVAILABLE
M02-GRF-008 same commit/snapshot on another branch may reuse graph content
M02-GRF-009 relevant untracked add detected by incremental refresh
M02-GRF-010 deleted/renamed/type changed entry invalidates affected graph
```

### 12.35.6 Potpie / Local-Only

```text
M02-POT-001 local attestation valid → provider allowed
M02-POT-002 external provider configured → block
M02-POT-003 telemetry enabled → block
M02-POT-004 Potpie crawler cannot ingest excluded sensitive/nested path
M02-POT-005 Potpie conflicts with current source → source wins
M02-POT-006 Potpie unavailable → no false FRESH/COMPLETE claim
```

### 12.35.7 Language Adapter / Multi-language

```text
M02-LNG-001 current Python AST implementation is wrapped without semantic regression
M02-LNG-002 .ts/.tsx/.mts/.cts map to TYPESCRIPT and ECMAScript family
M02-LNG-003 .js/.jsx/.mjs/.cjs map to JAVASCRIPT and ECMAScript family
M02-LNG-004 .java maps to JAVA
M02-LNG-005 unsupported language remains in SourceSnapshot but graph coverage becomes PARTIAL
M02-LNG-006 repository cannot register arbitrary language adapter/plugin
M02-LNG-007 TS/JS structural adapter never executes package.json scripts
M02-LNG-008 Java structural adapter never executes Gradle/Maven/plugin/annotation processor
M02-LNG-009 mixed Python+TS+Java repository merges normalized graph without dropping language scope
M02-LNG-010 cross-language edge requires explicit schema/config/runtime evidence
M02-LNG-011 semantic LSP request is routed through M06, never Host-side M02 execution
M02-LNG-012 adapter version change invalidates affected graph freshness
```

### 12.35.8 Parser / Resource Safety

```text
M02-PRS-001 malformed source does not crash agent
M02-PRS-002 oversized source bounded
M02-PRS-003 parser timeout bounded
M02-PRS-004 high file-count repository bounded
M02-PRS-005 unusual filename/newline/leading dash handled as structured data
```

---

## 12.36 Requirement Traceability

| M02 Requirement | Detailed Design |
|---|---|
| Repository 등록 / branch / commit / HEAD / operation | 12.4, 12.9 |
| Dirty tree / staged / unstaged / relevant untracked | 12.11, 12.12 |
| `working_tree_source_snapshot_hash` | 12.5, 12.12, 12.13 |
| canonical Repository traversal | 12.6, 12.7 |
| nested Repository / submodule ACL boundary | 12.8 |
| symlink / junction / mount boundary | 12.7 |
| `.git` ingestion 제외 | 12.6, 12.35 |
| alternates / partial clone / replace / sparse state | 12.9, 12.10 |
| implicit network fetch 금지 | 12.9.4, 12.10 |
| Graph commit + source snapshot binding | 12.16, 12.21 |
| Graph Freshness FRESH/STALE/PARTIAL | 12.21 |
| Incremental update | 12.22 |
| File relation | 12.23 |
| Function/method relation | 12.23 |
| Multi-language detection / adapter boundary | 12.15, 12.17, 12.18 |
| Unsupported language coverage / fail-conservative behavior | 12.15, 12.18, 12.35.7 |
| Potpie Local-Only | 12.19 |
| Structural Evidence Priority | 12.24 |
| Web/M09 조회용 durable reference | 12.25, 12.26 |

---

## 12.37 Implementation Order

```text
M02-01 domain enums / value objects
M02-02 Safe Git inspection primitives
M02-03 Git object/materialization inspector
M02-04 filesystem boundary detector
M02-05 policy-bounded SourceEnumerator
M02-06 M08-integrated SecureSourceReader
M02-07 SourceManifest canonical serializer / snapshot hash
M02-08 M09 SourceSnapshot persistence
M02-09 RepositoryContextService
M02-10 StructuralLanguageRegistry + PythonStructuralAdapter wrapper
M02-11 normalized static graph provider
M02-12 GraphSnapshot persistence
M02-13 GraphFreshnessEvaluator
M02-14 incremental ChangedSource/ChangedSymbol detection
M02-15 Potpie local-only adapter
M02-16 file/symbol relation query API
M02-17 ECMAScriptStructuralAdapter (TS/JS phase 2)
M02-18 JavaStructuralAdapter (phase 3)
M02-19 security / large-repository / cross-platform / multi-language integration tests
```

M02-02 Safe Git primitives는 M01/M05와 공통 구현을 사용한다. M02용 편의 wrapper가 보안 profile을 우회해 일반 `git` subprocess를 만들지 않는다.

---

## 12.38 M02 Detailed Design Review Corrections

작성 후 M02 요구사항과 대조하면서 다음 설계 보정을 반영한다.

1. **Git diff-only snapshot 금지**  
   `git status/diff`만으로 source scope를 정의하지 않고 filesystem traversal + relevant untracked + ingestion policy를 합성하도록 수정했다.

2. **`.gitignore`를 security/source authority로 사용하지 않음**  
   ignored path라도 policy상 relevant source면 snapshot 후보가 될 수 있게 했다.

3. **Git dirty와 analysis-source dirty를 내부적으로 분리**  
   mutation gate의 dirty semantics와 Graph/source freshness semantics를 혼동하지 않도록 `git_dirty / analysis_source_dirty`를 분리하되, 외부 mutation gate에는 보수적인 Git dirty를 제공한다.

4. **Sensitive exclusion은 자동 PARTIAL이 아님**  
   정책상 의도적으로 제외된 source는 scope 정의의 일부로 취급하고, missing/unreadable/unsafe coverage와 구분했다.

5. **Graph branch binding 과잉 제한 제거**  
   Graph content freshness는 exact commit/source/policy에 묶고, 동일 content를 가리키는 다른 branch에서는 graph artifact를 재사용할 수 있게 했다. 현재 branch는 분석 결과 context에 별도 binding한다.

6. **Nested Repository 탐지와 ACL을 분리**  
   M02가 parent ACL을 근거로 nested content를 읽지 않고, candidate boundary만 탐지한 뒤 M01 authorization을 별도로 요구하도록 했다.

7. **Potpie endpoint 문자열만으로 Local 판정하지 않음**  
   Docker internal network 같은 배포를 고려하여 M08 runtime attestation + network policy를 authority로 사용한다.

8. **Graph provider가 arbitrary path를 직접 open하지 못하게 함**  
   모든 source read는 `SecureSourceReader`를 통하도록 바꿨다.

9. **Incremental update correctness gate 추가**  
   policy/schema/boundary/provider semantics가 바뀌면 incremental refresh보다 full rebuild를 선택하도록 했다.

10. **Snapshot/Graph durable publish ordering 보강**  
    artifact/provider persistence가 완료되지 않았는데 metadata를 먼저 authoritative COMPLETE로 노출하지 않도록 publish 순서를 명시했다.

11. **Target language와 Agent implementation language 분리**  
    Agent Core가 Python으로 작성됐다는 사실과 분석 대상 language support를 분리했다. Python은 현재 structural/toolchain/effective support 모두 PARTIAL이며, 기존 Python AST 구현을 새 structural adapter 계약으로 migration·conformance한 뒤 해당 structural layer만 ACTIVE로 승격할 수 있다. TS/JS와 Java는 adapter contract를 가진 PLANNED capability로 명시한다.

12. **M02 structural adapter와 M06/M07 toolchain adapter 분리**  
    Java Gradle/Maven, TypeScript tsserver/Jest, Python pytest 같은 실행 경로가 M02 Host-side parser 권한으로 승격되지 않도록 non-executing structural boundary와 sandbox-backed execution boundary를 분리했다. M02에는 `StructuralLanguageRegistry`만 주입하고 toolchain registry 자체를 노출하지 않는다.

13. **Unsupported language를 silent success로 처리하지 않음**  
    source snapshot에는 남기되 graph coverage를 PARTIAL로 내리고, behavior-changing verification에서 required capability 부재를 M07 `NOT_AVAILABLE/INCONCLUSIVE`로 전달하도록 했다.

14. **Multi-language graph와 cross-language edge 보수화**  
    이름 유사성만으로 Python↔Java↔TS 호출관계를 확정하지 않고 schema/config/runtime evidence가 있을 때만 cross-language dependency edge를 authoritative evidence로 인정한다.

14-A. **Language family / effective support 상태 정규화**  
    `DetectedLanguage.family`의 자유 문자열을 `LanguageFamily` enum으로 교체하고, Python을 `ACTIVE`로 과장하지 않도록 `structural_status / toolchain_status / effective_status`를 분리했다. 현재 Python은 세 상태 모두 PARTIAL이며, structural adapter migration/conformance 완료 후 structural layer만 독립적으로 ACTIVE 승격할 수 있다. `.mts/.cts`도 TypeScript family에 포함한다.

14-B. **UNBORN 구현 gap 명시**  
    Detailed Design의 `HeadState.UNBORN`과 현재 `MetadataInspector` 구현 사이 차이를 known gap으로 기록했다. symbolic HEAD의 branch ref가 없는 경우를 무조건 `UNBORN`으로 추정하지 않고, 안전하게 확인하기 전에는 mutation readiness를 부여하지 않는다.

15. **Sparse / partial clone을 전체 Repository로 오인하지 않도록 수정**  
    materialization scope와 completeness를 SourceSnapshot/Graph freshness에 연결했다.

16. **Safe Git에서 implicit network와 executable integrations 차단 명시**  
    object가 없으면 자동 fetch하지 않고 PARTIAL/BLOCKED Evidence로 반환한다.

17. **`git status`를 무조건 Trusted command로 두지 않음**  
    clean/smudge/process filter나 fsmonitor 실행 가능성을 고려해, non-executing profile이 입증되지 않으면 index + filesystem evidence로 status를 합성하고 불확실한 path는 보수적으로 처리한다.

18. **Durable Graph data binding 추가**  
    `COMPLETE` GraphSnapshot은 restart 후에도 조회 가능한 `graph_data_ref`의 durability/integrity가 확인된 경우에만 publish하도록 했다.

19. **Nested Repository authorized case도 parent graph와 분리**  
    별도 ACL이 있더라도 parent snapshot에 병합하지 않고 별도 RepositoryContext로 분석하도록 경계를 명확히 했다.

20. **Potpie security violation과 availability failure 분리**  
    단순 장애는 secondary provider degradation으로 처리할 수 있지만 external provider/telemetry/egress 위반은 전체 Code Intelligence를 BLOCK한다.

21. **Adapter version을 Graph/Verification identity에 포함**  
    source가 같아도 structural adapter semantics가 바뀌면 기존 graph를 `FRESH`로 재사용하지 않도록 `language_adapter_set_hash`를 GraphSnapshot/DB/freshness 조건에 추가하고, Verification Basis에도 structural/toolchain adapter version set을 연결했다.

22. **Multi-language Risk 누락 보강**  
    API/cross-language boundary와 unsupported/toolchain-gap을 M04 Risk Evidence로 전달하여 adapter 부재가 안전한 0점으로 축소되지 않게 했다.

이 보정 이후 M02 요구사항의 source identity / graph freshness / traversal boundary / Local-Only intent와 충돌하는 known issue는 현재 설계 범위에서 발견되지 않았다.

---

# 13. M03 — Planner / Request Intent 설계 방향

## 13.1 Planner Result

```python
@dataclass(frozen=True)
class PlannerResult:
    domain: Domain
    task: Task
    reasoning_intent: ReasoningIntent

    resolved_query: str
    target_entities: tuple[TargetEntity, ...]

    needs_retrieval: bool
    needs_runtime_evidence: bool
    needs_impact_analysis: bool
    needs_clarification: bool

    acceptance_criteria: tuple[AcceptanceCriterion, ...]
```

## 13.2 Immutable Request Intent

LLM 호출 이전에 Trusted Orchestrator가 생성한다.

```python
@dataclass(frozen=True)
class RequestIntent:
    request_intent_id: RequestIntentId
    user_id: UserId
    repository_id: RepositoryId

    command_type: CommandType

    protected_request_ref: ArtifactRef
    request_hash: str

    created_at: datetime
```

LLM output은 기존 `request_intent_id`를 변경할 수 없다.

## 13.3 Acceptance Mapping

```python
@dataclass(frozen=True)
class AcceptanceMapping:
    request_intent_id: RequestIntentId
    criteria: tuple[AcceptanceCriterion, ...]
    mapping_version: str
    mapping_hash: str
    assumptions: tuple[str, ...]
```

`AcceptanceCriteriaMapper`는 원 요청 reference와 각 criterion의 provenance를 연결한다. 사용자 요청에서 확정할 수 없는 criterion은 `ASSUMED`로 표시하거나 `needs_clarification=true`를 유발하며, clarification 상태에서는 modification/destructive execution을 시작하지 않는다.

---

# 14. M04 — Risk Engine 설계 방향

Risk score는 deterministic Rule Engine에서 계산한다.

```text
ImpactAnalyzer
      ↓
RiskFactorCollector
      ↓
RiskRuleEngine
      ↓
RiskScore
      ↓
RiskLevel
```

Rule interface 후보:

```python
class RiskRule(Protocol):
    id: str
    version: str

    def evaluate(
        self,
        context: RiskContext,
    ) -> RiskFactorResult: ...
```

Risk factor 후보:

```text
caller_count
coverage
external_boundary
persistence
security
mode_change
symlink
gitlink
runtime_hotspot
language_boundary
unsupported_language_evidence
verification_toolchain_gap
```

Multi-language 변경은 단순 파일 수가 아니라 boundary 의미를 Risk Evidence에 포함한다.

```text
Spring API contract + Next.js client 동시 변경
→ cross-language / API boundary factor

behavior-changing file인데 structural/toolchain adapter 부재
→ missing evidence로 기록
→ 0점 처리 금지
→ Verification Plan 보수적 확대
```

핵심 원칙:

```text
UNKNOWN != 0
```

Missing evidence를 안전한 값 0으로 자동 축소하지 않는다.

Risk result type은 분리한다.

```text
PreliminaryRiskResult
FinalChangeRiskResult
```

`FinalChangeRiskResult`는 반드시 `canonical_change_set_id / final_diff_hash / risk_rule_version / threshold_version`에 바인딩하며, Patch revision 또는 final diff가 바뀌면 재사용하지 않는다.

---

# 15. M05 — Patch / Worktree / Source Consistency 설계 방향

M05 주요 Component:

```text
PatchProposalFactory
PatchCanonicalizer
PatchRepository

SafeGitAdapter

WorktreeManager
WorktreeRegistry

PatchApplyEngine

CanonicalChangeSetBuilder
SourceConsistencyChecker

RepositoryLockManager

ApplyCoordinator
ApplyRecoveryCoordinator
```

---

# 16. Safe Git Adapter

Git invocation을 일반 subprocess 호출과 분리한다.

```python
class SafeGitAdapter(Protocol):
    def inspect_repository(...): ...
    def create_worktree(...): ...
    def status(...): ...
    def diff_raw(...): ...
    def remove_worktree(...): ...


class SecurePatchApplyEngine(Protocol):
    def apply_to_worktree(...): ...
    def apply_to_repository(...): ...
```

1차 구현:

```text
SubprocessSafeGitAdapter
```

필수 실행 원칙:

```text
shell = false
argv array only
minimal environment
bounded timeout
bounded output
NUL-safe parsing
```

Git environment 예:

```text
GIT_CONFIG_NOSYSTEM=1
GIT_CONFIG_SYSTEM=/dev/null
GIT_CONFIG_GLOBAL=/dev/null
HOME=<isolated empty home>
GIT_TERMINAL_PROMPT=0
GIT_ASKPASS=<trusted-fail helper>
GIT_PAGER=cat
PAGER=cat
GIT_EDITOR=true
GIT_SEQUENCE_EDITOR=true
GIT_OPTIONAL_LOCKS=0          # read-only introspection profile
GIT_LFS_SKIP_SMUDGE=1
```

실행 가능한 Git integration은 기본 차단한다.

```text
credential.helper
core.hooksPath
external diff
textconv
clean/smudge process filter
fsmonitor
pager
editor
submodule auto update
implicit network fetch
```

필요한 integration은 pre-registered trusted profile에서만 허용한다.

호출자가 주입할 수 있는 `GIT_DIR / GIT_WORK_TREE / GIT_OBJECT_DIRECTORY / GIT_ALTERNATE_OBJECT_DIRECTORIES / GIT_CONFIG_* / SSH_*` 등 repository/object/network boundary를 바꾸는 환경변수는 기본 제거한다. Diff/introspection은 `--no-ext-diff`, textconv 비활성화 등 command별 안전 옵션을 강제하고, path 목록은 NUL-delimited 또는 structured parser로 처리한다.

**중요:** SafeGitAdapter는 repository materialization/introspection용 trusted boundary다. 실제 Patch file mutation의 authority는 `SecurePatchApplyEngine + SecureFilesystem`에 두며, 검증된 operation manifest를 단순 `git apply` 명령에 다시 위임하지 않는다. Gitlink/mode 등 Git metadata operation이 필요한 경우에도 별도 preflight + trusted plumbing으로 제한한다.

---

# 17. Secure Filesystem / openat2

Linux에서는 filesystem mutation security를 단순 `realpath()` 검사에 의존하지 않는다.

Repository root를 directory handle로 anchor한다.

```text
dirfd = open(repository_root)
```

이후 가능한 경우 `openat2()` 기반으로 relative path를 resolve한다.

Regular-file mutation의 parent/target resolve 기본 policy:

```text
RESOLVE_BENEATH
RESOLVE_NO_SYMLINKS
RESOLVE_NO_MAGICLINKS
RESOLVE_NO_XDEV
```

단, symlink 자체를 생성/삭제/target 변경하는 operation은 leaf symlink를 dereference하면 안 되므로 parent directory만 위 policy로 resolve한 뒤 `fstatat(..., AT_SYMLINK_NOFOLLOW) / readlinkat / symlinkat / renameat2` 등 no-follow API를 사용한다. 즉 `RESOLVE_NO_SYMLINKS`를 모든 operation에 기계적으로 동일 적용하지 않는다.

File open flag 후보:

```text
O_NOFOLLOW
O_CLOEXEC
```

핵심 mutation model:

```text
repository root dirfd
+
validated relative path
→ openat2 / *at family
```

absolute path 문자열을 신뢰 boundary로 사용하지 않는다.

`openat2()`가 없는 kernel/platform에서는 security level을 조용히 낮추지 않는다. Linux fallback은 각 path component를 `openat(O_PATH|O_DIRECTORY|O_NOFOLLOW)` 방식으로 dirfd walk하고 `fstat`/mount identity를 검증하는 구현으로 제한하며, 동등한 안전성을 보장할 수 없으면 해당 mutation operation을 fail-closed한다.

---

## 17.1 Secure Filesystem Interface

```python
class SecureFilesystem(Protocol):
    def inspect(...): ...
    def create_file(...): ...
    def replace_file(...): ...
    def remove(...): ...
    def mkdir(...): ...
```

구현:

```text
LinuxSecureFilesystem
WindowsSecureFilesystem
```

Linux 후보:

```text
openat2
O_NOFOLLOW
dirfd
statx
mount id
device/inode identity
```

Windows 후보:

```text
CreateFileW
FILE_FLAG_OPEN_REPARSE_POINT
GetFinalPathNameByHandle
FileIdInfo
VolumeSerialNumber
reparse tag validation
```

OS별 path security를 하나의 문자열 canonicalization 함수로 억지 통합하지 않는다.

---

## 17.2 Hardlink / Mount / Alias 방어

Symlink 차단만으로 충분하지 않다.

검사 대상:

```text
hardlink
bind mount
mount point
junction
reparse point
filesystem boundary
protected object alias
```

기존 regular file 수정은 **in-place write를 기본 금지**하고 같은 trusted directory 안에 새 inode를 생성하여 fsync 후 `renameat2`/동등 atomic replace를 사용한다. 이 방식은 외부 hardlink alias에 원본 inode mutation이 전파되는 것을 방지한다.

`st_nlink > 1`인 대상의 chmod/mode mutation처럼 inode metadata가 다른 hardlink에 전파될 수 있는 operation도 replacement semantics로 처리하거나 fail-closed한다. mount/reparse/protected-object alias가 탐지되거나 안전성을 증명할 수 없으면 fail-closed한다.

---

# 18. Canonical Actual Change Set

Final Risk / Guardrail / Verification authority는 사람이 읽는 `git diff` text가 아니라 Canonical Actual Change Set이다.

최소 operation type:

```text
CREATE
MODIFY
DELETE
RENAME
COPY
MODE_CHANGE
SYMLINK_CHANGE
GITLINK_CHANGE
```

각 entry 후보:

```text
normalized_path
operation
entry_type_before
entry_type_after
mode_before
mode_after
preimage_hash
postimage_hash
symlink_target_before
symlink_target_after
source_manifest_origin
```

Patch apply engine manifest + Git structured status + filesystem evidence를 결합한다.

`final_diff_hash`는 Canonical Actual Change Set의 deterministic canonical serialization에 바인딩한다.


## 18.1 Canonical Serialization / Hash

1차 integrity hash는 `SHA-256`으로 통일하고 모든 hash에 `algorithm + schema_version`을 함께 저장한다.

Canonical representation은 versioned deterministic JSON을 사용하되 filesystem path는 display string을 직접 normalization하지 않고 **OS에서 관찰한 relative path byte representation을 reversible encoding(base64url 등)** 으로 저장한다. case-fold / Unicode normalization 충돌 검사는 별도의 filesystem collision key로 수행하며, 실제 path identity를 임의 변환한 값을 hash input으로 사용하지 않는다.

Canonical object는 key ordering, integer/string encoding, null handling을 고정하고 timestamps / process-local IDs처럼 동일 source state에서 달라질 값을 Change Set hash input에 포함하지 않는다.

---

# 19. M06 — Sandbox Architecture

Sandbox backend를 abstraction으로 분리한다.

```python
class SandboxBackend(Protocol):
    def execute(
        self,
        spec: SandboxSpec,
    ) -> SandboxResult: ...
```

backend interface 구현:

```text
DockerSandboxBackend       # v1 필수
MicroVMSandboxBackend      # hardened deployment 선택 구현
```

---

# 20. Container / microVM 전략

## 20.1 v1 기본

```text
rootless Docker 또는 Podman
+
seccomp
+
AppArmor/SELinux
+
network none
+
read-only rootfs
+
non-root user
+
cgroup limits
```

## 20.2 Hardened Deployment

추가 backend 후보:

```text
Firecracker
Kata Containers
gVisor
```

1차 구현을 특정 microVM runtime에 강하게 결합하지 않는다.

---

# 21. Sandbox Profile

최소 두 profile을 구분한다.

```text
verification-default
profiling-ptrace
```

`verification-default`는 ptrace capability를 기본 허용하지 않는다.

`py-spy` 등 별도 profiling capability가 필요한 경우에만 `profiling-ptrace`를 사용한다.

Network profile은 별도로 분리한다.

```text
runtime-offline              # default, --network none
runtime-internal-allowlist   # explicit M08 network decision 필요
restore-internal-mirror      # dependency restore 전용
```

`runtime-internal-allowlist`는 broad bridge access가 아니라 destination/protocol/port가 제한된 dedicated network namespace + egress proxy/firewall policy로 구현한다. Sensitive `runtime-read`와 결합하려면 별도 combined decision이 있어야 한다.

---

# 22. Docker / Container 기본 Hardening

개념적 flag baseline:

```bash
docker run \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --memory 2g \
  --cpus 2 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=512m \
  --tmpfs /output:rw,nosuid,nodev,size=1g \
  ...
```

위 수치는 Architecture baseline 예시이며 exact quota는 profile configuration에서 versioning한다.

기본 mount layout:

```text
/workspace/src      verified runtime-safe source view (read-only 기본)
/workspace/out      writable output
/tmp                bounded tmpfs
/home/sandbox       empty ephemeral HOME
```

Writable source가 불가피한 command는 별도 writable copy profile을 사용하고 M07 source-integrity check를 mandatory로 연결한다.

기본 금지:

```text
host HOME
host credential
SSH_AUTH_SOCK
GPG socket
docker.sock
host PID namespace
host IPC namespace
host network namespace
arbitrary host Unix socket
device pass-through
main Repository/worktree writable .git metadata
```

---

# 23. Seccomp / Capability Baseline

기본 Verification profile에서 차단 후보:

```text
mount
umount2
pivot_root
ptrace
bpf
perf_event_open
kexec_load / kexec_file_load
reboot
swapon
swapoff
keyctl
add_key
request_key
setns
unshare
```

일부 syscall은 container runtime / language runtime compatibility 테스트 후 exact profile에서 확정한다.

권한이 추가되는 profiling profile은 일반 Verification profile과 분리한다.

---

# 23.1 Offline Dependency Restore Architecture

Dependency restore와 untrusted project execution은 동일 sandbox/network authority를 공유하지 않는다.

```text
DependencyResolver
→ lockfile / resolved-set inspect
→ local cache / prebuilt image 우선
→ 필요 시 restore-internal-mirror sandbox
→ immutable dependency manifest + origin/digest 기록
→ runtime sandbox에는 credential/network authority 미전달
```

Repository install/build hook은 restore host process에서 실행하지 않는다. dependency 자체 build가 필요하면 Repository source/credential을 마운트하지 않은 dependency-builder sandbox를 사용한다. project hook이 검증에 필수이면 별도의 network-off untrusted project sandbox에서 실행한다.

Public PyPI/npm/Maven/GitHub download는 기본 차단하며, required dependency를 재현할 수 없으면 해당 check는 `NOT_AVAILABLE` 또는 정책에 따라 `INCONCLUSIVE`가 된다.

# 23.2 Result Collection / Parser Safety

```text
SandboxResultCollector
→ size/quota enforcement
→ SecretDetector / Redactor
→ SensitiveResultClassifier
→ safe artifact parser
→ M09 store
```

ANSI/control sequence/HTML/SVG/Markdown script-like content는 display-safe representation으로 변환한다. XML external entity, archive path traversal, template execution 등 active parser feature는 비활성화한다. 안전한 redaction을 보장할 수 없는 raw result는 protected artifact로 격리하거나 폐기한다.

# 24. M06 Command Policy

LLM이 raw shell string을 직접 생성 / 실행하지 않는다.

금지 모델:

```text
"pytest && curl ..."
```

허용 모델:

```python
ToolRequest(
    tool=ToolId.PYTEST,
    args=PytestArgs(
        targets=("tests/test_x.py",),
        quiet=True,
    )
)
```

Execution pipeline:

```text
ToolRequest
↓
CommandPolicyEngine
↓
RegisteredCommandTemplate
↓
argv[]
↓
SandboxBackend
```

---

## 24.1 LanguageToolchainAdapter

언어별 test/build/static/profile 특성은 M02 structural parser와 분리하여 M06/M07가 소비하는 trusted adapter로 정의한다.

```python
class LanguageToolchainRegistry(Protocol):
    def resolve(self, language: LanguageId) -> "LanguageToolchainAdapter | None": ...
    def toolchain_capabilities(self, language: LanguageId) -> frozenset[LanguageCapability]: ...


class LanguageToolchainAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    languages: frozenset[LanguageId]

    def inspect_capabilities(
        self,
        metadata: TrustedProjectMetadataView,
        baseline_inventory: BaselineToolchainInventory,
    ) -> LanguageToolchainCapabilities: ...

    def static_check_requests(self, target: VerificationTarget) -> tuple[ToolRequest, ...]: ...
    def unit_test_requests(self, target: VerificationTarget) -> tuple[ToolRequest, ...]: ...
    def build_requests(self, target: VerificationTarget) -> tuple[ToolRequest, ...]: ...
    def profile_requests(self, target: ProfilingTarget) -> tuple[ToolRequest, ...]: ...
```

`LanguageToolchainRegistry`는 M06/M07 trusted wiring에서만 제공하고 M02에는 노출하지 않는다. Adapter는 command를 실행하지 않고 registered `ToolRequest`만 생성한다. Repository의 `package.json scripts`, Gradle task, Maven plugin 선언은 capability/evidence 후보일 뿐 자동 실행 authority가 아니다.

언어별 계획:

```text
Python
├─ static: ruff + trusted type checker(mypy/pyright policy에 따라)
├─ test: pytest
├─ CPU: cProfile, process CPU, optional py-spy profiling profile
└─ memory: tracemalloc, ru_maxrss/cgroup memory.peak, optional memray/Scalene

TypeScript / JavaScript
├─ static: trusted tsc --noEmit / ESLint template
├─ semantic: tsserver/TypeScript service in sandbox
├─ test: Jest/Vitest registered template
├─ build: trusted Node toolchain template; arbitrary npm script direct execution 금지
│          (필요한 project script는 explicit pre-registration + sandbox execution만 허용)
└─ profile: Node/V8 CPU profile + heap profile/snapshot + cgroup peak

Java
├─ static/semantic: JDT LS or trusted compiler/static analyzer in sandbox
├─ test: JUnit via trusted Maven/Gradle toolchain template
├─ build: pinned Maven/Gradle binary; repository wrapper script를 Host에서 직접 실행 금지
│          wrapper metadata/version은 Evidence로 읽고, 필요한 project build는 sandbox에서 trusted binary/template로 실행
├─ CPU/runtime: JFR / process CPU
└─ memory: GC log / JFR / optional heap dump protected artifact
```

Java annotation processor, Gradle/Maven plugin, Node loader/plugin처럼 project code를 실행할 수 있는 기능은 전부 untrusted project execution으로 취급하여 M06 Sandbox를 우회하지 않는다.

---

# 25. Command Template Registry

Repository 내부 config는 test/build command를 제안할 수 있으나 authority가 아니다.

Trusted registry 예:

```text
Python
  pytest / python -m pytest
  ruff
  mypy / pyright
  coverage

TypeScript / JavaScript
  tsc --noEmit
  eslint
  jest / vitest
  trusted Node build template

Java
  trusted Maven test/build template
  trusted Gradle test/build template
  JUnit-oriented test selector
  JFR / GC logging profile template

Common
  registered benchmark command
```

현재 저장소 구현은 `python-pytest-v1`만 실제 compile path가 존재한다. 위 TS/JS/Java 항목은 Detailed Design target이며 template implementation/conformance test 전에는 runtime registry에 등록하지 않는다.

각 template는 최소 다음을 갖는다.

```text
template_id
version
language / language_family
executable / trusted binary digest-or-image binding
allowed arguments
path argument rules
project metadata constraints
toolchain fingerprint requirement
timeout ceiling
sandbox profile
network requirement
output limit
```

---

# 26. M08 — Policy Engine / DSL

1차 policy DSL은 **YAML 기반 declarative configuration으로 확정**한다. 단, authority-bearing policy는 Repository 내부 파일에서 읽지 않는다.

```text
Trusted Local Policy Store
~/.knowledge-hub/policy/   (예시, repository root 밖)
```

- owner/admin-controlled filesystem permission 적용
- `policy_version / schema_version / content_hash` 기록
- YAML safe loader 사용, custom tag/object construction 금지
- duplicate key / schema unknown field를 fail-closed
- parse 후 typed policy model + JSON Schema(또는 동등 schema) validation
- Repository config는 policy suggestion/metadata일 뿐 exception/permission을 self-authorize하지 못함

예:

```yaml
version: security-v1

sensitive:
  rules:
    - id: dotenv
      paths:
        - ".env"
        - ".env.*"
      classification: SECRET

    - id: private-key
      paths:
        - "**/*.pem"
        - "**/*.key"
      classification: SECRET

defaults:
  read_context: deny
  runtime_read: deny
  modify: deny
  declassify: deny
  remote_publish: deny
```

---

# 27. Sensitive Exception DSL

예:

```yaml
exceptions:
  - id: exc-2026-001
    policy_version: security-v1
    decision_id: pd_01
    issued_by: admin_01
    issued_at: "2026-09-13T00:00:00Z"

    repository_id: repo_123

    principal:
      user_id: user_456

    operation: runtime-read

    paths:
      - "tests/fixtures/private-test.env"

    expires_at: "2026-10-01T00:00:00Z"

    network:
      allow: false
```

독립 operation:

```text
read-context
runtime-read
modify
declassify
remote-publish
```

한 exception이 다른 operation을 암묵적으로 허용하지 않는다.

---

# 28. Combined High-Risk Exception

Sensitive runtime-read + network access는 개별 예외 두 개가 존재한다는 이유만으로 자동 결합하지 않는다.

별도 combined decision을 요구한다.

```yaml
combined_exceptions:
  - id: combined-001
    repository_id: repo_123
    runtime_read_decision_id: pd_runtime_01
    network_decision_id: pd_network_01
    destinations:
      - host: artifact.internal
        protocol: https
        port: 443
    expires_at: "2026-10-01T00:00:00Z"
```

Combined decision은 두 underlying decision의 scope/expiry/current authorization을 모두 다시 검증한다.

---

# 28.1 Sensitive Classification / Runtime Security Verification

M08은 path pattern만으로 민감도를 결정하지 않는다.

```text
SensitivePathClassifier
SecretContentScanner
SensitiveDecisionEngine
RuntimeSecurityVerifier
```

`SecretContentScanner`는 ingestion/LLM context 이전에 high-confidence credential/private-key/token pattern을 검사하며, 탐지된 raw content를 모델에 넣은 뒤 마스킹하는 방식으로 대체하지 않는다.

`RuntimeSecurityVerifier`는 Code Intelligence 실행 전/중 다음 상태를 versioned status로 검증한다.

```text
LLM Provider        LOCAL
Embedding           LOCAL
Repository          LOCAL
Code Graph          LOCAL
Potpie              LOCAL
Telemetry           DISABLED
External API        DISABLED
Internet Egress     BLOCKED
```

필수 Local-Only 조건이 충족되지 않으면 분석/Retrieval/LLM execution을 차단한다.

# 29. Sensitive Provenance

Sensitive `read-context` / `runtime-read` Evidence가 downstream artifact에 영향을 주면 trusted orchestrator가 provenance를 전파한다.

대상:

```text
answer
analysis result
plan
patch
verification artifact
benchmark artifact
remote source
```

LLM이 provenance label을 생략하거나 제거 요청을 해도 자동 제거하지 않는다.

---

# 30. M07 — Verification Domain

Planner interface 후보:

```python
class VerificationPlanner:
    def create_plan(
        self,
        risk: FinalRisk,
        acceptance: AcceptanceMapping,
        project: ProjectCapabilities,
    ) -> VerificationPlan:
        ...
```

Check model:

```python
@dataclass(frozen=True)
class VerificationCheck:
    check_id: VerificationCheckId
    type: CheckType
    required: bool
    source: EvidenceProvenance
    command_template_id: str | None
```

결과 상태:

```text
PASS
FAIL
INCONCLUSIVE
NOT_APPLICABLE
NOT_AVAILABLE
```

Aggregate rule:

```text
required FAIL
→ FAILED

no required FAIL
+ required INCONCLUSIVE / NOT_AVAILABLE 존재
→ INCONCLUSIVE

all required PASS / valid NOT_APPLICABLE
→ VERIFIED
```

Test / toolchain provenance는 최소 다음을 구분한다.

```text
BASELINE_EXISTING_TEST
PATCH_MODIFIED_TEST
PATCH_ADDED_TEST
GENERATED_EPHEMERAL_CHECK
TRUSTED_EXTERNAL_HARNESS
PATCH_MODIFIED_VERIFICATION_TOOLCHAIN
```

Patch가 기존 required test를 삭제/skip/discovery 축소하거나 검증 toolchain 자체를 바꾼 경우 독립 Evidence 없이 그 변경된 검증 경로만으로 `VERIFIED`를 만들지 않는다.

Performance/OPTIMIZE required benchmark는 반복 측정, warmup, dataset hash, environment fingerprint, dependency origin/digest, baseline/post-patch harness provenance를 기록한다. 비의도적 환경 차이 또는 변동성 때문에 개선 여부를 확정할 수 없으면 required benchmark는 `INCONCLUSIVE`다.

---

## 30.1 Multi-language Verification Planning

`VerificationPlanner`는 Repository의 대표 언어 하나가 아니라 **Canonical Actual Change Set이 건드린 language set + cross-language boundary**를 기준으로 required checks를 합성한다.

```text
Changed Python only
→ Python required checks

Changed TS/JS only
→ ECMAScript required checks

Changed Java only
→ JVM required checks

Changed Spring API + Next.js client
→ Java checks ∪ TS checks ∪ API/integration boundary check

Changed unsupported behavior source
→ required capability NOT_AVAILABLE
→ overall INCONCLUSIVE
```

`ProjectCapabilities`는 Repository metadata self-report가 아니라 trusted language registry, baseline inventory, lockfile/toolchain evidence, M06 availability를 조합하여 생성한다.

```python
@dataclass(frozen=True)
class ProjectLanguageCapability:
    language: LanguageId
    family: LanguageFamily
    structural_status: LanguageSupportStatus
    toolchain_status: LanguageSupportStatus
    effective_status: LanguageSupportStatus
    capabilities: frozenset[LanguageCapability]
    structural_adapter_id: str | None
    structural_adapter_version: str | None
    toolchain_adapter_id: str | None
    toolchain_adapter_version: str | None
    environment_fingerprint_ref: str | None
```

Patch가 adapter/toolchain config를 새로 추가해 자기 자신의 support status를 `ACTIVE`로 승격시키거나 required check를 `NOT_APPLICABLE`로 면제하지 못한다. baseline inventory 또는 trusted administrative registration으로 교차 확인한다.

언어별 profiling evidence는 공통 `ProfilerResult`로 normalize하되 raw 의미를 잃지 않는다.

```text
Python       → allocation / process peak / cProfile evidence
TS/JS        → V8 CPU/heap + process/cgroup evidence
Java         → JFR/GC/heap + process/cgroup evidence
```

Heap dump, V8 heap snapshot 등 대형/민감 artifact는 일반 Audit payload에 저장하지 않고 M08 classification을 거친 protected artifact 경로를 사용한다.

---

# 31. Verification Basis

`verification_basis_id`는 단순 임의 UUID가 아니라 아래 authority를 integrity-link 해야 한다.

```text
request_intent_id
acceptance mapping hash/version
patch_id/revision
final_diff_hash
risk_rule_version
threshold_version
verification plan/version
guardrail policy version
command policy version
sandbox profile version
security exception decision reference
NOT_APPLICABLE decision reference
structural language adapter set/version reference
toolchain adapter/template version set
toolchain / environment fingerprint
```

Patch / policy / required evidence가 달라졌는데 이전 basis를 재사용하지 않는다.

---

# 32. Verification Source Integrity

Verification 실행 전후 exact source snapshot을 비교한다.

```text
before snapshot
→ command execution
→ after snapshot
```

변경 발견 시:

```text
Evidence invalid
→ source restore
→ exact Patch snapshot rebuild
→ required check re-run
```

반복적으로 source mutation을 제거할 수 없으면 `INCONCLUSIVE`.

---

# 33. M10 — Web Control Plane Architecture

Web은 Local Store DB를 직접 임의 조회하지 않는다.

```text
Next.js
↓
Spring Boot
↓
Code Intelligence Query API
↓
M09 Store
```

다음 조회는 current ACL / RBAC를 다시 적용한다.

```text
Graph
Patch detail
Canonical Change Set
Verification
Approval Evidence
Audit
Sensitive artifact
Security status
```

과거 ACL snapshot은 현재 권한을 대신하지 않는다.

Raw artifact viewer / protected download는 일반 dashboard rendering과 분리한다.

Repository path/source snippet/diff/test output/audit reason은 untrusted text로 렌더링하며 HTML/SVG/Markdown/ANSI를 active UI markup으로 실행하지 않는다. Next.js/Spring 양쪽에서 output encoding/content-type 정책을 고정하고, raw protected artifact는 current ACL + sensitive-result policy를 통과한 별도 endpoint에서만 제공한다.

---

# 34. M11 — Integration / Acceptance

M11은 구현 코드보다 E2E contract / failure scenario verification 비중이 높다.

대표 scenario:

```text
TC-E2E-001
normal optimize → verify → approve → apply

TC-E2E-002
proposal base stale

TC-E2E-003
pre-apply sensitive block

TC-E2E-004
patch apply failure

TC-E2E-005
verification source mutation

TC-E2E-006
approval persistence failure

TC-E2E-007
apply lock unavailable

TC-E2E-008
crash immediately after repository apply

TC-E2E-009
partial apply / result mismatch

TC-E2E-010
approval authorization revoked before apply

TC-E2E-011
verification basis policy mismatch

TC-E2E-012
sensitive runtime-read + network combined exception missing

TC-E2E-013
orphan worktree / sandbox recovery

TC-E2E-014
remote operation exact applied-result mismatch
```

---

# 34.1 Optional Remote Operation Architecture

Remote publish/PR/Merge는 Local Apply와 별도 authority다.

```text
RemoteOperationCoordinator
RemoteAuthorizationService
InternalGitProviderAdapter
RemoteSourceMaterializer
RemoteReconciler
```

선행조건:

```text
local lifecycle = APPLIED
explicit remote intent 또는 trusted workflow authorization
current Remote permission
exact patch_id/revision/post_apply_result_hash binding
allowlisted internal provider
필요 시 M08 remote-publish + declassify decision
```

Remote source는 현재 mutable working tree 전체를 암묵적으로 사용하지 않고 verified canonical artifact / exact applied snapshot에서 hash-bound immutable source로 materialize한다. side effect 전 durable `remote_operation_id`를 기록하고 timeout/crash 후 provider state를 reconcile하여 duplicate PR/Merge를 방지한다.

# 35. Repository Lock / Apply Serialization

Knowledge Hub 내부 Apply에는 Repository write lock 또는 동등한 serialization을 사용한다.

lock은 다음을 보장해야 한다.

```text
Knowledge Hub 내부 apply serialization
crash recovery
stale lock detection
owner identity
release on every exit path
```

다만 외부 editor / Git command / process의 변경까지 lock이 절대 차단한다고 가정하지 않는다.

따라서 lock과 별도로 다음이 필수다.

```text
pre-apply source consistency
per-target preimage validation
post-apply result integrity
```

---

# 36. Apply Attempt Durable Intent

Repository filesystem mutation 전에 다음을 durable하게 기록한다.

```text
apply_attempt_id
patch_id
revision
patch_hash
final_diff_hash
verification_result_id
verification_basis_id
approval_binding_id
pre_apply_source_hash
expected_post_apply_result_hash
```

DB persistence 실패 시 filesystem side effect를 시작하지 않는다.

---

# 37. Apply Recovery

Recovery decision:

```text
Current Repository State
↓
PRE_APPLY_MATCH
→ 동일 verified artifact Apply retry 가능

EXPECTED_POST_APPLY_MATCH
→ 중복 Apply 금지
→ previous Apply success로 reconcile

OTHER / PARTIAL / UNKNOWN
→ STALE_VERIFICATION
→ remediation required
```

Recovery는 새로운 Approval event를 자동 생성하지 않는다.

---

# 38. Remediation Boundary

Partial Apply / unknown mutation / post-apply mismatch가 발생하면 자동 retry를 금지한다.

```text
remediation required
↓
clean / consistent Repository recovery
↓
new source baseline
↓
re-analysis
↓
re-verification
↓
re-approval
```

Remediation 완료 전:

```text
Apply Recovery 금지
자동 Re-analysis 금지
자동 Re-verification 금지
Remote Operation 금지
```

---

# 39. Implementation Order

요구사항 문서의 phase를 실제 구현 dependency 관점에서 더 세분화한다.

```text
DD-00  Shared Domain / typed IDs / canonical serialization
       ↓
DD-01  M09 DB + Audit/Event transaction
       ↓
DD-02  M01 Identity / Repository ACL
       ↓
DD-03  M02 Safe Repository Inspection + Source Snapshot + StructuralLanguageRegistry/Python adapter
       ↓
DD-04  M08 Policy Engine
       ↓
DD-05  M05 SafeGit + SecureFilesystem
       ↓
DD-06  M03 Planner / Request Intent
       ↓
DD-07  M04 Impact / Risk
       ↓
DD-08  M06 Command Policy + Sandbox + language toolchain contract
       ↓
DD-09  M07 Verification / Profiling / Benchmark (Python first, TS/JS then Java)
       ↓
DD-10  M05 Patch Lifecycle / Apply / Recovery
       ↓
DD-11  M10 Web Control Plane
       ↓
DD-12  M11 E2E Acceptance / Traceability
```

---

# 40. M09를 선행 구현하는 이유

Architecture상 거의 모든 authority 상승이 durable persistence에 의존한다.

예:

```text
VERIFIED authority
Approval eligibility
APPROVED state
Apply Attempt Intent
Crash reconciliation
Canonical verified Patch restore
Security decision provenance
```

따라서 Patch lifecycle을 먼저 구현하고 나중에 persistence를 덧붙이는 방식은 피한다.

M09의 transaction / artifact durability / audit semantics를 먼저 확정한다.

---

# 41. 모듈별 Detailed Design에서 반드시 내려가야 하는 수준

앞으로 모듈 문서에서 다음과 같은 추상 표현만 남기지 않는다.

예:

```text
"Safe Git을 사용한다"
```

으로 끝내지 않고:

```text
SafeGitAdapter
SubprocessSafeGitAdapter
argv construction
sanitized env
Git config blocking
hook/filter blocking
object source validation
timeout
exit mapping
NUL-safe parser
```

까지 내려간다.

또한:

```text
"symlink를 막는다"
```

으로 끝내지 않고 Linux 기준:

```text
openat2
RESOLVE_BENEATH
RESOLVE_NO_SYMLINKS
RESOLVE_NO_MAGICLINKS
RESOLVE_NO_XDEV
O_NOFOLLOW
dirfd
hardlink identity
mount boundary
```

까지 정의한다.

Sandbox도:

```text
"격리한다"
```

으로 끝내지 않고:

```text
backend
runtime argv / flags
seccomp
AppArmor / SELinux
uid/gid
mount layout
tmpfs
cgroup
network namespace
environment allowlist
output quota
cleanup
crash reconciliation
```

까지 확정한다.

---

# 42. Requirement vs Detailed Design 구분

기존 v1.10 요구사항이 Product / Security Intent의 authority다.

본 Architecture / Detailed Design 문서는 다음을 수행한다.

```text
Requirements
→ 구현 가능한 구조로 구체화
```

다음을 수행하지 않는다.

```text
새로운 사용자 기능 임의 추가
Verification requirement 임의 완화
Local-Only 정책 완화
Sensitive policy scope 확대
Approval semantics 변경
```

SQLite / Typer / YAML DSL / Docker 등의 구체 기술 선택은 현재 Architecture baseline 결정이며, 요구사항의 사용자 기능 의미 자체를 바꾸는 것은 아니다.

---

# 43. Detailed Design 문서 운영 방식

M01~M11 상세설계를 별도 Markdown 11개로 다시 만들 필요는 없다. 이미 요구사항이 모듈별 문서로 분리되어 있으므로 설계까지 동일하게 분할하면 cross-cutting contract와 version이 쉽게 drift한다.

본 파일을 Architecture / Detailed Design의 **단일 master**로 유지하고 아래 순서로 각 모듈 섹션을 점진적으로 완성한다.

```text
M01 → M02 → M03 → M04 → M05 → M06 → M07 → M08 → M09 → M10 → M11
```

별도 파일로 분리하는 것은 다음 기계적/대형 산출물에 한정한다.

```text
design/appendices/schema.sql
design/appendices/policy.schema.json
design/appendices/openapi.yaml
design/appendices/seccomp/*.json
design/appendices/apparmor/*
design/appendices/sequence/*.mmd
```

각 appendix는 master 문서에서 `schema_version / content_hash`로 참조한다. 실제 코드 구현은 `DD-00 ~ DD-12 Implementation Order`를 따른다. 즉 문서 서술 순서와 구현 dependency 순서는 구분한다.

---

# 44. 최종 Baseline 결정 요약

현재 Architecture baseline:

```text
Agent Core            Python
Target languages      Python PARTIAL (Structural PARTIAL / Toolchain PARTIAL) / TypeScript·JavaScript PLANNED / Java PLANNED
Language boundary     StructuralLanguageRegistry/Adapter(M02) + LanguageToolchainRegistry/Adapter(M06/M07)
CLI                   Typer
Web                   Next.js + Spring Boot
AI / RAG              FastAPI + Local LLM
Local DB              SQLite + WAL + FULL synchronous
Artifact              Filesystem + DB metadata/integrity binding + protected encryption
IPC                   Unix Socket 또는 localhost-only HTTP
Git                   SafeGitAdapter abstraction
Git implementation    sanitized subprocess profile (introspection/materialization only)
Patch mutation         SecurePatchApplyEngine + SecureFilesystem
Filesystem Linux      dirfd + operation-specific openat2/*at + atomic replacement
Filesystem Windows    handle / reparse-point 기반 별도 구현
Sandbox v1            rootless Docker/Podman
Sandbox hardened      optional microVM / gVisor / Kata / Firecracker backend
Command execution     structured ToolRequest + registered templates
Policy                 trusted-store versioned declarative YAML DSL
Audit                  append-only event + atomic materialized state update
Patch authority        Canonical Actual Change Set
Verification authority finalized verification_basis_id
Apply                  durable intent + lock + pre/post integrity
Recovery               pre/post expected-state reconciliation
Remote                 APPLIED exact-result bound internal-provider operation only
Web access             current ACL re-check + display-safe rendering
```

이 baseline을 기반으로 M01부터 class / schema / sequence / error model / test case까지 상세설계를 진행한다.


---

# 45. Review Corrections Applied

본 revision에서 다음 설계 문제를 수정했다.

- M08을 M07 뒤의 단방향 dependency처럼 표현하던 diagram을 cross-cutting security/policy layer로 수정
- SQLite 가정을 `single-user`가 아닌 `single-node/local control-plane`으로 수정하고 local-filesystem/WAL 운영 제약 추가
- filesystem artifact + SQLite 사이 crash window를 staged durable-write + orphan reconciliation로 명시
- SafeGitAdapter에서 direct Patch apply responsibility를 제거하고 SecurePatchApplyEngine으로 mutation authority 분리
- `openat2 RESOLVE_NO_SYMLINKS`를 모든 operation에 일괄 적용하지 않고 regular-file/symlink operation별 no-follow semantics로 분리
- hardlink alias 전파를 줄이기 위해 regular-file modification 기본을 atomic replacement로 강화
- Safe Git environment에서 repo/object/network boundary를 바꾸는 환경변수와 executable integration 차단을 구체화
- M06 offline dependency restore, internal network profile, output sanitization / safe parser architecture 보강
- M08 policy authority를 Repository 밖 trusted store로 고정하고 safe YAML/schema validation 추가
- M08 path + content sensitive classification 및 Local-Only RuntimeSecurityVerifier 추가
- M07 test/toolchain provenance / benchmark reproducibility rule 보강
- M10 untrusted output rendering policy 보강
- M11 optional Remote Operation coordinator / exact applied-result binding 추가
- SHA-256 + versioned canonical serialization 기준 추가
- M01~M11 상세설계를 별도 11개 파일로 복제하지 않고 본 integrated master에서 관리하도록 문서 운영 원칙 확정
- M01 Detailed Design에서 invalid session의 weaker OS identity silent fallback을 금지하고, Apply Recovery를 generic dirty-tree block과 분리
- M01 Approval Evidence에 protected request reference / Verification Basis policy refs / INCONCLUSIVE·NOT_AVAILABLE 표시와 post-confirmation revalidation을 구체화
- M01 Repository identity를 shared repository ID와 per-worktree root ID로 분리하고 SQLite identity mapping DDL shape를 추가
- M01 Approval durable-write/transaction 실패 시 VERIFIED 유지 fail-closed 분기와 Recovery exact binding tuple을 sequence에 명시
