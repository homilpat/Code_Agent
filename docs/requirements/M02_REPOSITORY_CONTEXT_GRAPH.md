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
