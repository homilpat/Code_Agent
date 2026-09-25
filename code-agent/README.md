# Knowledge Hub Code Agent

v1.10 설계를 구현 중인 Python CLI 패키지입니다. 기존 Spring/Next.js/RAG 앱과 분리된 trusted orchestration core입니다. 현재 범위는 로컬 저장·권한 검사·제한된 Python 정적 조회 및 명시적으로 검토한 한 파일의 실험적 테스트·적용입니다. 전체 v1.10 acceptance 완료를 의미하지 않습니다.

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
# 별도 파일에 작성한 JSON 수정 후보의 diff만 확인 (저장소에 쓰지 않음)
uv run kh preview-candidate /home/user/candidate.json --repo /home/user/projects/example
# localhost LM Studio 호환 서버에서 로드된 모델로 한 Python 파일의 수정안만 생성
uv run kh modify "반환값을 고쳐줘" --target src/example.py --model "$LOCAL_MODEL_ID" --port 1234 --repo /home/user/projects/example
# 같은 요청에서 생성된 후보를 저장소에 적용하지 않고 격리된 pytest로 시험
uv run kh modify "반환값을 고쳐줘" --target src/example.py --model "$LOCAL_MODEL_ID" --image "$TRUSTED_IMAGE_ID" --test tests/test_example.py --repo /home/user/projects/example
# 관리자 사전 빌드 이미지의 immutable ID와 테스트 경로를 지정해 임시 후보만 시험
uv run kh verify-candidate /home/user/candidate.json --image "$TRUSTED_IMAGE_ID" --test tests/test_example.py --repo /home/user/projects/example
# preview-candidate 출력의 candidate_hash/source_snapshot_hash/target_state_digest를 직접 확인한 뒤
# 지정한 한 파일을 다시 격리 테스트하고 통과하면 원본 worktree 파일을 교체
uv run kh apply-candidate /home/user/candidate.json --reviewed-hash "$CANDIDATE_HASH" --reviewed-source-hash "$SOURCE_SNAPSHOT_HASH" --reviewed-target-digest "$TARGET_STATE_DIGEST" --image "$TRUSTED_IMAGE_ID" --test tests/test_example.py --repo /home/user/projects/example
# 적용이 중간에 끊겼다면 status에 표시된 attempt ID로 실제 파일의 현재 내용만 재확인
uv run kh reconcile-write "$ATTEMPT_ID" src/example.py --repo /home/user/projects/example
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
| 로컬 DB | SQLite WAL/FULL/FK, schema version, append-only audit hash chain의 재시작 검사, state/event 원자적 저장, idempotency |
| 신원·권한 | Linux UID 명시적 mapping, invalid session fallback 금지, stable repository/root 등록, current ACL |
| status | ACL 이후 Safe Git으로 HEAD/index/worktree/operation을 검사하고 dirty·불확실성과 내부 파일 교체의 미완료 기록을 구분. 원자적 캡처는 아님 |
| explain | Python 파일의 클래스·함수·import·호출 표현식. 코드 실행·LLM 호출 없음 |
| impact | absolute import-name 기반 후보. import root/runtime/call target 해석은 미완료로 표시 |
| source scanner | Linux openat2, nested repo/mount/alias/sensitive exclusion, 크기·시간·개수 제한 |
| graph 저장 | 소스·builder·정책에 연결된 hash, AST 구조 JSON과 감사 이벤트 원자적 저장 |
| Patch domain | regular create/modify/delete canonicalization, trusted base binding, in-memory preview, actual manifest 비교. `apply-candidate`는 수동 검토한 한 Python 파일의 실험적 교체. 정식 patch `apply`는 미연결 |
| Patch 저장 | proposal/revision, 검증 plan/result/basis의 원자적 저장, VERIFIED revision 전용 내부 승인 기록, artifact integrity, 재시작 audit/state 확인 |
| Risk domain | versioned weighted integer scoring, missing evidence interval, 보수적 상한 기반 level, preliminary/final 구분 |
| Command policy | 제한된 pytest targets, 고정 argv/env, image digest 기반 Podman 실행 backend. `verify-candidate`, `modify --image --test`, `apply-candidate`의 실험적 후보 테스트에 연결 |
| Python LSP | 격리된 pyright 서버와 통신하는 bounded client(내부 API). explain/impact에는 미연결 |
| 로컬 모델 후보 | loopback OpenAI 호환 서버에 한 Python 파일과 요청을 보내고, 단일 파일 수정 후보의 diff를 제공. 선택적으로 해당 후보를 임시 source view에서 Podman pytest 실행 |
| YAML 정책 | bounded SafeLoader, tag/anchor/alias/duplicate/unknown field 거부, owner-private 외부 store에서 로드 |

운영 CLI의 `modify`는 `--target`과 `--model`을 모두 주면 loopback 로컬 모델의 후보를 검사하고 diff를 반환합니다. `--image`와 하나 이상의 `--test`를 같이 지정하면 생성 직후 임시 후보를 Podman에서 시험합니다. `CHANGE_PROPOSE`, `CODE_ANALYZE`, `PATCH_VERIFY` 권한을 확인하고, 생성 후와 테스트 후 저장소 상태를 재검사합니다. `MODEL_TEST_EXPERIMENTAL` 결과에는 후보·diff·테스트 출력이 포함되며 `apply_ready=false`입니다. 파일 적용은 하지 않습니다. 옵션 없이 호출하거나 `profile`, `optimize`, `verify`, `apply`를 사용하면 `CAPABILITY_NOT_AVAILABLE`을 반환합니다. 내부 patch/store/command API는 다음 구현 단계의 trusted service가 사용하는 라이브러리이며, 임의 candidate/RPC에서 직접 호출하는 권한 API가 아닙니다.

모델 호출은 지정한 한 Python 파일(최대 32 KiB)과 요청만 `127.0.0.1`의 OpenAI 호환 `/v1/chat/completions`로 보냅니다. 응답은 최대 1 MiB이며 다른 파일, 비정형 출력, 민감 변경을 거부합니다. `MODEL_PREVIEW_ONLY` 응답의 `candidate` 필드만 JSON 파일로 저장하면 `verify-candidate`의 입력으로 사용할 수 있습니다. 테스트 명령은 그때의 source/Git/권한을 다시 확인합니다. 모델 응답과 테스트 성공은 검증·승인·적용 근거가 아닙니다. 모델 서버가 실행 중이지 않으면 실패합니다.

`preview-candidate`는 저장소 밖에 있는 JSON 파일의 `{"operations":[{"path":"app.py","operation":"modify","content":"...전체 새 파일 내용..."}]}` 형식을 받습니다. 현재 한 Python 파일만 지원합니다. `CHANGE_PROPOSE`와 `CODE_ANALYZE` 권한을 확인하고 안전한 source view에서 diff를 계산합니다. AI가 내용을 생성하거나 테스트·저장·적용하지 않으며, 반환되는 PARTIAL snapshot hash는 승인/적용 권한이 아닙니다.

`verify-candidate`는 같은 수동 후보의 임시 Python source view에서 등록된 pytest 경로를 rootless Podman으로 실행합니다. `CHANGE_PROPOSE`, `CODE_ANALYZE`, `PATCH_VERIFY` 권한이 필요하며 이미지 ID는 미리 빌드된 immutable digest여야 합니다. 결과는 `EXPERIMENTAL_TEST_ONLY`/`apply_ready=false`입니다. source snapshot이 PARTIAL인 상태이므로 pytest PASS도 정식 Patch Verification·승인·적용 근거가 아닙니다. Podman과 이미지가 준비되지 않았으면 거부합니다.

`apply-candidate`는 미리보기에서 받은 후보·소스·Git 기준 해시 3개를 모두 요구합니다. `CHANGE_PROPOSE`, `CODE_ANALYZE`, `PATCH_VERIFY`, `PATCH_APPROVE`, `PATCH_APPLY` 권한을 확인하고, immutable Podman 이미지에서 지정된 pytest가 PASS한 후 한 기존 Python 파일만 worktree에서 교체합니다. 생성 중이거나 검증 중에 기준이 바뀌면 거부하고, 교체 전후 상태를 다시 읽습니다. 결과의 `EXPERIMENTAL_APPLIED`/`formal_verification=false`는 정식 `APPROVED`/`APPLIED` 패치 상태가 아닙니다. 검사에 사용한 PARTIAL source snapshot과 실제 Podman 테스트 환경의 한계를 그대로 유지합니다. 변경 전 Git commit으로 원본을 보존하고 후보·diff·세 해시를 직접 검토해야 합니다.

내부 `replace_source_file`은 기존 Python 파일 하나의 원본 해시·파일 신원·symlink·hardlink를 검사하고 임시 파일을 fsync한 뒤 같은 디렉터리에서 교체합니다. `WorktreeWriteJournal`은 교체 전 시작 기록에 후보·테스트 증명 해시를 묶고, 완료 기록이 없으면 같은 저장소의 다음 journaled write를 막으며, `status`는 미완료 수·ID와 `mutation_ready=false`를 표시합니다. `reconcile-write`는 현재 파일 바이트가 원본/교체본 중 어느 쪽인지 확인해 기록합니다. 다른 내용이거나 링크로 바뀐 파일은 거부합니다. 이 관찰은 정식 검증이나 승인을 대신하지 않으며, 교체본이 남았다면 Git worktree는 dirty 상태입니다. 내부 `PatchStore.approve_revision`은 정식 `VERIFIED` 상태의 저장된 패치에 한해 patch/basis/target digest와 현재 승인 권한을 묶은 감사 기록을 남깁니다. `kh apply`는 여전히 거부합니다. 정식 적용에는 COMPLETE 제안 기준이 필요합니다. 외부 프로세스의 동시 수정을 완전히 막는 원자적 Git 캡처도 아직 없습니다.

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

- `status`는 고정 plumbing Git 명령으로 HEAD 객체·index·worktree를 검사합니다. ignore 규칙과 관계없이 정책상 제외되지 않은 untracked 파일도 변경으로 기록하고, mutation gate는 두 번의 검사를 대조합니다. 그래도 전체 repository의 원자적 snapshot, 두 검사 사이의 일시적 변경, 이후 적용 시점의 동일성을 증명하지 않습니다. 실제 apply 연결 시 기준 snapshot과 적용 직전 상태를 재검사해야 합니다.
- 내장 ingestion 정책은 `.pyc`, `.pyo`, `.log` 생성 파일을 source view와 untracked 변경 판정에서 제외합니다. 이미 Git이 추적하는 파일의 변경은 계속 검사합니다. 그 밖의 ignored 파일은 내용에 영향을 줄 수 있으므로 보수적으로 변경으로 처리합니다.
- Source/graph는 현재 `PARTIAL`입니다. Safe Git target 검사와 source scanner는 별도 경로로, 둘 사이의 원자적 일치나 완전한 object-source authorization을 증명하지 않습니다. graph 결과를 mutation base로 승인하지 않습니다.
- AST는 구문 evidence입니다. 함수 실행, 동적 import, import root와 호출 대상의 최종 해석은 수행하지 않습니다. 파싱 실패를 전체 성공으로 숨기지 않습니다.
- 민감 데이터는 경로 검사 후 읽고 다시 콘텐츠 검사합니다. 내장 detector가 모든 secret을 찾아낸다고 보장하지 않습니다. 발견된 파일은 AST·일반 graph persistence 대상에서 제외합니다.
- FileArtifacts는 Linux 전용입니다. 암호화 키 저장소가 없으므로 SENSITIVE/PROTECTED artifact는 저장을 차단합니다. Orphan을 자동 삭제하지 않고 조회합니다.
- 기존 DB를 열 때 audit hash chain을 확인합니다. 프로세스 실행 중 모든 조회에서 재검사하지는 않으며, 마지막 이벤트 삭제나 전체 DB 교체는 DB 밖의 보호된 체크포인트 없이는 확인할 수 없습니다.
- 내부 Podman backend는 rootless/cgroup v2/seccomp를 확인하고 runtime-safe source view에서 등록된 pytest 명령과 pyright 서버를 실행합니다. 로컬에 이미지가 없으면 통합 테스트가 skip됩니다. `.github/workflows/code-agent-sandbox.yml`은 Linux CI에서 두 이미지를 먼저 빌드하고 rootless/cgroup v2를 확인한 뒤 통합 테스트를 실행합니다. 이미지 준비 또는 실행 실패는 CI 실패이며 skip을 정상 검증으로 보지 않습니다. 이 workflow의 실제 GitHub 실행 결과는 별도로 확인해야 합니다. CLI의 `verify`와 `explain`/`impact` LSP 연결은 아직 제공하지 않습니다.
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
