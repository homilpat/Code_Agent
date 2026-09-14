# Knowledge Hub Code Agent

v1.10 설계를 구현 중인 Python CLI 패키지입니다. 기존 Spring/Next.js/RAG 앱과 분리된 trusted orchestration core입니다. 현재 배포 범위는 로컬 저장·권한 검사와 제한된 Python 정적 조회입니다. 전체 v1.10 acceptance 완료를 의미하지 않습니다.

## 실행

지원 운영 환경은 WSL2 Ubuntu/Linux, Python 3.11 이상이며 소스와 저장소는 Linux 파일시스템에 둡니다. `openat2`를 지원하는 x86_64/aarch64 Linux 커널이 필요합니다. Windows에서는 개발 테스트와 `doctor`를 실행할 수 있습니다.

```bash
# 프로젝트 자체의 개발 환경 준비. 대상 저장소의 runtime dependency restore와 별개입니다.
uv sync --extra dev --locked
uv run kh doctor
uv run kh init
uv run kh repo register /home/user/projects/example
uv run kh status --repo /home/user/projects/example
uv run kh explain src/example.py --repo /home/user/projects/example
uv run kh impact src/example.py --repo /home/user/projects/example
uv run kh history --repo /home/user/projects/example
```

`--store`는 최상위 옵션입니다: `kh --store /home/user/private-kh status --repo ...`.
기본 저장 경로는 `~/.knowledge-hub`이고 저장소 밖의 owner-only Linux ext4/xfs/btrfs 경로여야 합니다. Windows의 `.venv`는 WSL로 복사하지 않고 Linux에서 다시 생성합니다.

Windows 개발 환경:

```powershell
.venv/Scripts/python.exe -m kh_agent doctor
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
```

## 현재 기능

| 영역 | 구현 범위 |
|---|---|
| 공통 domain | 타입별 UUID4 ID, revision, canonical JSON/SHA-256, reversible path bytes, lifecycle/readiness |
| 로컬 DB | SQLite WAL/FULL/FK, schema version, append-only audit, state/event 원자적 저장, idempotency |
| 신원·권한 | Linux UID 명시적 mapping, invalid session fallback 금지, stable repository/root 등록, current ACL |
| status | ACL 이후 Git HEAD/loose·packed branch/operation metadata. object resolution/dirty 상태는 미확인으로 표시 |
| explain | Python 파일의 클래스·함수·import·호출 표현식. 코드 실행·LLM 호출 없음 |
| impact | absolute import-name 기반 후보. import root/runtime/call target 해석은 미완료로 표시 |
| source scanner | Linux openat2, nested repo/mount/alias/sensitive exclusion, 크기·시간·개수 제한 |
| graph 저장 | 소스·builder·정책에 연결된 hash, AST 구조 JSON과 감사 이벤트 원자적 저장 |
| Patch domain | regular create/modify/delete canonicalization, trusted base binding, in-memory preview, actual manifest 비교 |
| Patch 저장 | proposal/revision, 검증 plan/result/basis의 원자적 저장, artifact integrity, 재시작 audit/state 확인 |
| Risk domain | versioned weighted integer scoring, missing evidence interval, 보수적 상한 기반 level, preliminary/final 구분 |
| Command policy | 제한된 pytest targets, 고정 argv/env, image digest 기반 Docker 계획. 실제 실행 backend는 아직 없음 |
| YAML 정책 | bounded SafeLoader, tag/anchor/alias/duplicate/unknown field 거부, owner-private 외부 store에서 로드 |

운영 CLI의 `modify`, `profile`, `optimize`, `verify`, `apply`는 아직 `CAPABILITY_NOT_AVAILABLE`을 반환합니다. 내부 patch/store/command API는 다음 구현 단계의 trusted service가 사용하는 라이브러리이며, 임의 candidate/RPC에서 직접 호출하는 권한 API가 아닙니다.

## 권한 모델

`kh init`은 현재 Linux UID를 private store의 로컬 관리자로 명시적으로 등록합니다. 초기화된 저장소에서 다른 UID로 bootstrap을 반복해 관리자가 되는 경로는 차단됩니다. 등록 관리자가 `repo register`를 실행하면 그 관리자에게 해당 저장소의 권한을 부여합니다. 이후에는 관리자도 저장소별 현재 권한 검사를 통과해야 합니다.

```bash
kh access add-user 1001
kh access grant usr_... repo_... CODE_ANALYZE
kh access revoke usr_... repo_... PATCH_APPLY
```

현재 local store가 UID mapping/ACL authority입니다. 별도 Linux UID 간 private store 공유나 Spring JWT credential bridge는 아직 구현하지 않았습니다. 이 CLI를 네트워크 API로 공개하거나 기존 Spring 역할과 자동으로 동일하다고 간주하면 안 됩니다.

## 정책

기본 ingestion policy는 trusted package 안의 `security/ingestion.py`입니다. `.gitignore`나 Repository의 YAML/README는 정책 authority로 읽지 않습니다. 명시적 정책이 있으면 `~/.knowledge-hub/policy/security.yaml` 한 위치에서만 로드합니다. 파일 mode는 0600이어야 합니다.

`config/policy.example.yaml`은 관리자가 검토할 예시이며 자동 적용하지 않습니다. 예시 위험 가중치는 생산 검증된 점수 체계가 아닙니다. `kh policy-check`로 현재 외부 정책의 schema와 content hash를 검사합니다. 정책 버전명이 같아도 실제 내용이 달라지면 해시가 달라집니다. 예외 승인/인터넷 허용/민감 데이터 해제 DSL은 아직 지원하지 않아 해당 unknown field를 거부합니다.

Risk evidence provider가 아직 연결되지 않은 요소는 `UNAVAILABLE`입니다. 이 경우 exact `score`는 null이고 상한 기준으로 검증 범위를 확대합니다. `impact`는 정책이 없으면 Risk `NOT_AVAILABLE`, 정책이 있으면 아직 근거가 없는 요소를 명시한 PRELIMINARY interval을 반환합니다.

## 검증과 운영 한계

- 참조 조회는 loose ref를 우선하고 없으면 최대 4 MiB의 `packed-refs`를 검사합니다. 중복·잘못된 경로·혼합 OID 길이를 거부하고, 파일 읽기 전후 및 HEAD/ref 재조회로 변경을 검사합니다. 원자적 snapshot이나 객체 존재 검증은 아니며 symbolic ref chain/reftable은 아직 지원하지 않습니다. Git 명령·설정·hook은 실행하지 않습니다.
- Source/graph는 현재 `PARTIAL`입니다. Git index/packed object/object-source authorization, dirty 상태 및 repository 전체의 atomic snapshot은 아직 구현하지 않았습니다. 이 결과로 mutation base를 승인하지 않습니다.
- AST는 구문 evidence입니다. 함수 실행, 동적 import, import root와 호출 대상의 최종 해석은 수행하지 않습니다. 파싱 실패를 전체 성공으로 숨기지 않습니다.
- 민감 데이터는 경로 검사 후 읽고 다시 콘텐츠 검사합니다. 내장 detector가 모든 secret을 찾아낸다고 보장하지 않습니다. 발견된 파일은 AST·일반 graph persistence 대상에서 제외합니다.
- FileArtifacts는 Linux 전용입니다. 암호화 키 저장소가 없으므로 SENSITIVE/PROTECTED artifact는 저장을 차단합니다. Orphan을 자동 삭제하지 않고 조회합니다.
- Docker 계획에는 network none, read-only source/rootfs, non-root, capability 제한, cgroup/tmpfs 자원 제한과 immutable image가 포함됩니다. 계획 생성은 격리 검증이나 명령 실행이 아닙니다. rootless/LSM/seccomp/runtime-safe source, timeout/output quota/cleanup을 검증하는 backend가 다음 단계입니다.
- `PatchStore.finish_verification` 테스트는 trusted 입력에 대한 **저장 일관성** 검증입니다. 실제 repository test/sandbox/approval/apply 성공을 뜻하지 않습니다.

## 파일 위치

```text
src/kh_agent/
  core/        공통 ID/hash/state
  identity/    사용자 식별
  access/      permission matrix와 readiness
  repository/  identity/metadata/source scanner
  analysis/    Python AST graph와 risk scoring
  patch/       canonical proposal/change set
  security/    ingestion/YAML/openat2
  sandbox/     structured command/container plan
  store/       schema/audit/registry/patch/artifact/graph
  cli/         Typer entry point
tests/         platform-independent와 Linux-only 테스트
```

진행 기록은 상위 요구사항 폴더의 `IMPLEMENTATION_PROGRESS.md`, 재시작 기록은 `RESTART_HANDOFF.md`입니다. 요구사항 원본과 문서 검증 보고서는 수정하지 않습니다.
