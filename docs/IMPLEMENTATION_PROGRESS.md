# Code Agent 구현 진행 기록

기준일: 2026-09-15 (Asia/Seoul), 마지막 코드 검증: 2026-09-15

## 2026-09-15: 설계 테스트 ID ↔ 테스트 매핑

- `tests/conftest.py`에 다음을 추가했다.
  - `@pytest.mark.req("M01-UT-002", partial=False)` marker
  - `docs/ARCHITECTURE_DETAILED_DESIGN_v1.10.md`에서 테스트 ID를 읽어 marker를 검증한다. 모르는 ID, 빈 marker, 오타 옵션은 수집 단계에서 실패한다.
  - `pytest --req-report`로 확인·일부·없음 개수와 목록을 출력한다.
  - 검증 로직 자체의 테스트: `tests/test_requirement_ids.py`
- 설계서에 정의된 테스트 ID는 M01·M02의 111개뿐이다. M01-FR 같은 요구사항 참조는 테스트 ID가 아니며, M03 이후 모듈은 설계서에 테스트 ID가 없다.
- 매핑 원칙: 설명된 동작을 실제로 단언하는 테스트만 확인으로 표시한다. 명령을 거치지 않고 게이트 함수만 보는 테스트, 설계보다 엄격하게 다르게 구현된 경우는 `partial`이다.
- 구현됐는데 테스트가 없던 12개에 테스트를 추가했다:
  - 세션 인증 성공
  - 선택자 생략 + 리비전 1개
  - symlink 별칭·linked worktree·다른 clone의 저장소 identity
  - merge·rebase·cherry-pick·revert·sequencer 진행 중 상태
  - 저장소 안 symlink와 민감 파일 symlink 미추적
  - `.git` 파일 경계
  - 빌드 산출물 제외
  - 새 결함은 발견되지 않았다.
- 결과: **확인 30 / 일부 19 / 없음 62**. 남은 미커버는 미구현 기능(승인·적용, Git index·객체, freshness, TS/Java, Potpie), 알려진 결함(unborn HEAD), 권한 없이 만들기 어려운 경계(bind mount, Windows reparse)다.
- 테스트: Linux 165 passed / 1 skipped, Windows 157 passed / 9 skipped(Linux 전용과 symlink 권한), pyright 0 errors, ruff check/format 통과.

## 2026-09-15: Linux 첫 실행 검증과 정적 게이트(ruff S, pyright) 도입

- WSL2 Ubuntu 24.04(Python 3.12.3) ext4 작업 사본에서 전체 테스트 **146 passed / 1 skipped**(Windows 전용 1개). Windows에서 skip되던 openat2 스캐너·artifact 테스트 5개가 처음 실행돼 통과했다.
- Linux 저장소로 CLI를 처음 실사용했다: `doctor → init → repo register → status → explain → impact → history`는 모두 exit 0, 예약 명령 `modify`는 `CAPABILITY_NOT_AVAILABLE`(exit 2). 저장소 권한 700/600, audit 해시 체인 10건 검증 통과.
- 실사용에서 확인한 것:
  - `impact`가 `from pkg import util`로 대상을 쓰는 파일을 후보로 찾지 못한다(리뷰 결함 재현).
  - `explain`·`impact`는 `ACL_CHECKED`를 2회 기록한다. 소스 수집 뒤 재확인하는 의도된 동작이지만 두 기록을 구분하는 필드가 없다.
- ruff `S` 규칙을 추가했다(tests의 S101 제외). 지적 5건은 모두 오탐이라 사유를 적은 noqa로 처리했다: 검증 상태 문자열 `"PASS"`, sandbox 컨테이너 내부 `/tmp` 경로 3건, SafeLoader 하위 로더.
- pyright standard를 도입했다(`[tool.pyright]`, dev 의존성). 기존 오류 4건 수정:
  - `ChangeEntry`의 content·mode `None`을 명시적으로 거부(`patch/canonical.py` 2곳)
  - AST 순회 stack 타입 명시
  - 결과: basic·standard 모두 0 errors.
- 결과: Windows 142 passed / 5 skipped, Linux 146 passed / 1 skipped, ruff check/format 통과.

## 2026-09-15: 아키텍처 규약(22~32절) 차이 중 작은 3건 반영

- 검증 판정(`core/lifecycle.py`):
  - 필수 검사는 증거가 있는 `PASS`만 통과한다.
  - 호출자가 넣는 참조 문자열(`na_decision_reference`)만으로 `NOT_APPLICABLE` 면제가 되던 경로를 없애고, 필드도 삭제했다. 이 경우는 `INCONCLUSIVE`로 판정한다.
  - 조건부 필수(27.1절 `CONDITIONAL`)와 신뢰할 수 있는 적용성 판정이 생기면 다시 허용한다.
- 결과값 `ERROR` 추가(`core/enums.py`). 필수 검사가 `ERROR`면 `INCONCLUSIVE`이고, 선택 검사는 판정에 영향이 없다.
- audit 해시 체인(`store/schema.sql`, `store/database.py`):
  - 각 이벤트에 `previous_event_digest`와 `event_digest`를 저장한다. `event_digest`는 순번·내용·시각·이전 digest를 묶은 canonical hash다. 순번은 1부터 빈틈 없이 부여한다.
  - `verify_audit_chain`이 수정·순서 변경·중간 삭제를 탐지하고, `PatchStore.check_integrity`가 이를 호출한다.
  - 최신 이벤트 뒷부분만 잘라낸 경우는 마지막 digest를 외부에 보관해야 탐지할 수 있다(미구현).
- 스키마 v2. v1 저장소는 변환하지 않고 `SCHEMA_VERSION_UNSUPPORTED`로 거부한다. 과거 기록에 digest를 새로 붙이면 보호되지 않았던 이력을 인증하게 되기 때문이다.
- 결과: **142 passed / Linux 전용 5 skipped**, ruff check/format 통과.
- 수정 전 소스에서 새 테스트가 실패함을 확인했다: `test_domain` 2건 실패, `test_store`는 `verify_audit_chain`이 없어 import 실패.
- 다음: Safe Git object/index adapter(TargetSnapshot 형태). 상태 전이 재설계(26절)는 승인·적용 단계에서 한다.

## 2026-09-15: 코드 리뷰 선행 결함 3건 수정

아래 "코드 리뷰 결과" 표의 높음 2건과 `head_state`(중간)를 고쳤다.

- `repository/metadata.py`: 해석된 브랜치 HEAD는 `head_state=NORMAL`. ref 없음은 `UNRESOLVED`, raw oid는 `DETACHED` 유지.
- `security/policy.py`: 삭제·이동된 등록 저장소 경로는 store 포함 검사에서 제외한다. 존재하는 저장소 안의 store는 경로 순서와 무관하게 `ACCESS_DENIED`.
- `store/patches.py`: `propose()`는 `CanonicalProposal`만 받는다. intent·base commit·snapshot은 proposal base에서만 도출하고, intent의 repository와 다르거나 dict이면 `INVALID_INPUT`. `intent_id`·`base_commit`·`source_snapshot_hash` 인자는 제거했다.
- 회귀 테스트: loose·packed `NORMAL`, detached `DETACHED`, 삭제된 등록 저장소가 있어도 정책 로드 진행(순서 무관 `ACCESS_DENIED` 유지), 다른 저장소 base·raw payload 거부, 저장된 base 값이 proposal과 일치. 수정 전 소스에서 실패함을 확인했다.
- 결과: **136 passed / Linux 전용 5 skipped**, ruff check/format 통과. evals 과제 ca-001/002는 base commit `b8060c7` 고정이라 영향 없다.
- 다음: 요구사항 ID↔테스트 매핑, ruff `S`/pyright → Safe Git object/index adapter.

## 2026-09-14 오후 기록: 새 레포 이전, go/no-go 평가, 방향 전환(dev-guard)

사용자 요청으로 기록. 아래 내용이 이 문서의 기존 "다음 시작점"보다 최신이다.

### 1. 작업 위치 변경 (중요)

- 코드와 문서는 GitHub `homilpat/Code_Agent`(public)로 이전했다. 로컬 작업 폴더는 바탕화면 `Code_Agent`(git)다.
- 요구사항 폴더의 `blogProject/blogProject-main/code-agent/`는 git이 없는 **옛 사본**이다. 이후 수정하지 않는다.
- `homilpat/blogProject` 이력 13커밋을 그대로 이어받았고, 기존 레포에 `v1.0-blog` 태그를 달았다(새 레포에도 있음). `future-work/rag-search-pipeline` 브랜치(RAG 평가 파이프라인)도 새 레포로 옮겼다.
- `docs/`: 요구사항 동결 세트(SHA256 16개 일치, `.gitattributes`로 줄바꿈 변환 금지), 상세 설계서, 이 진행 기록(로컬 경로 가림). 재부팅 인수인계 기록은 공개 레포에서 제외했다.

### 2. Windows 간헐 실패 수정 (`b8060c7`)

- 증상: 같은 테스트를 20회 실행하면 6회 실패. 원인은 `read_metadata`의 파일 핸들(`fstat`)과 경로(`lstat`) 비교에서 Windows 경로 조회의 `st_ctime_ns`가 몇 ms 늦게 반영되는 것(측정 300회 중 21회 불일치).
- 수정: Linux가 아닌 환경에서만 핸들-경로 비교에서 ctime 제외. Linux는 모든 필드 비교 유지. 회귀 테스트는 수정 전 코드에서 실패함을 확인했다.
- 결과: 전체 테스트 20/20회 통과, **131 passed / Linux 전용 5 skipped**. 이전의 "129 passed" 기록에는 우연히 통과한 실행이 섞였을 수 있다. Linux 테스트는 여전히 미실행이다.

### 3. go/no-go 평가 러너 (`evals/`, `70fe604`)

- 구조: 고정 기준 커밋에서 임시 작업 폴더 생성 → 문제 설명과 문맥 파일 제공 → 모델은 SEARCH/REPLACE 블록으로만 답함(러너가 전부 적용 또는 전부 거부) → 숨김 테스트 포함 전체 테스트 → 실패 출력으로 최대 N회 재시도 → JSONL 기록. 실패 테스트는 최대 2회 재실행하고 `flaky`로 기록한다.
- 과제 2개(2026-09-14 코드 리뷰 결함): `ca-001` 정상 브랜치 `head_state` NORMAL, `ca-002` 삭제된 등록 저장소 때문에 정책 로드 실패. `validate`로 "기준 커밋에서 실패, 정답 패치로 전체 통과"를 3회 연속 확인했다.
- 모델 환경: LM Studio, `qwen/qwen3.6-35b-a3b` Q4_K_M(22.07GB), 문맥 32K, VRAM 14.8/16GB + 나머지 RAM, 약 8 tok/s. `mistralai/devstral-small-2-2512` Q4_K_M은 다운로드 중(기록 시점 88%, 속도 약 1MB/s).
- 첫 결과: **2/2 PASS**. ca-001 1회, ca-002 2회(첫 답이 시스템 프롬프트 예시의 `path/` 접두어를 그대로 써 APPLY_ERROR). 과제당 약 4분이며 대부분 모델 응답 시간이다.
- 판단: 과제가 쉽고(한 파일 몇 줄), 문맥 파일을 직접 지정했고, 과제 수가 부족해 **go/no-go 결론은 보류**. 기본 루프가 로컬 모델로 동작한다는 점은 확인했다.
- 주의: 두 결함은 평가 과제의 정답 패치로만 존재하고 **code-agent 제품 코드에는 아직 반영하지 않았다.**
- 평가용 Python venv는 임시 폴더에 만들었으므로 재개 시 다시 만들어야 한다: `python -m venv` 후 `pip install -e code-agent[dev]`, 저장소 루트에서 `python -m evals.runner validate` / `run --model ...`.

### 4. 상세 설계서 갱신 (`29a9784`)

- 사용자가 대상 언어 구조를 추가했다: Python PARTIAL / TS·JS phase 2 / Java phase 3, 비실행 structural adapter(M02)와 toolchain adapter(M06/M07) 분리, `LanguageFamily`, structural·toolchain·effective 상태 분리, `language_adapter_set_hash`, 다중 언어 검증 계획, `HeadState.UNBORN` 구현 공백 명시. 1차 리뷰 지적 4건(`SUPPORTED` 오기, Python ACTIVE 과장, `family: str`, `.mts/.cts`)은 반영됐다.
- 남은 지적: `effective_status` 결정 규칙의 "나머지 조합은 PARTIAL"이 PARTIAL 정의("일부 capability는 실제 사용 가능")와 모순된다. `PLANNED + UNSUPPORTED`처럼 사용 가능한 layer가 없으면 UNSUPPORTED여야 한다.
- 이 레포의 설계서는 14:21 수정본까지 반영했다. 14:26 수정본(`effective_status` 규칙 추가)은 아직 동기화하지 않았다.

### 5. 방향 논의와 결정

- QLoRA 등 파인튜닝은 지금 하지 않는다. 기준 측정과 학습 데이터가 없고, 틀·문맥·피드백 개선이 먼저다.
- 기업은 보통 계약(학습 금지·무보관), 자사 클라우드 경유, 관리형 설정·게이트웨이로 해결한다. 폐쇄망 로컬 에이전트는 망분리 등 틈새 수요다.
- 결정: 개발할 때 쓰는 **가드레일·품질 도구(dev-guard)를 별도 레포**로 만든다. 대상은 Claude Code와 Codex CLI 둘 다, 언어는 Python·TS/JS·Java. 원칙은 프롬프트가 아닌 결정적 검사로 강제, 효과가 측정된 기능만 추가, 외부 도구(Serena, Semgrep, claude-mem 등)는 코드를 복사하지 않고 연결.
- v1.10 전체 구현을 중단한다는 결정은 하지 않았다. 우선순위가 dev-guard로 옮겨졌다.

### 6. dev-guard 1단계 (`homilpat/dev_guards`, public, `d3d37b2`)

- 요구사항 폴더의 규칙(M06, M08, 요구사항 민감 파일 목록, code-agent `ingestion.py`·`sandbox/policy.py`, 이 문서의 모델 금지 사항)을 hook으로 옮겼다. 규칙 18개, 각 규칙에 근거 문서를 연결했다.
- 조정: M08 "외부 LLM API 금지"는 민감 파일 차단 + `local-only` 저장소 차단으로 바꿨다. 일반 비밀값 할당, 패키지 설치, `git push`, 작업 폐기 git 명령, 분석 불가 명령은 차단 대신 확인. Codex hook은 확인 창이 없어 확인 규칙도 차단하고 execpolicy `prompt` 규칙을 함께 생성한다.
- 검증: 테스트 112개 통과(생성한 규칙을 실제 `codex execpolicy check`로 확인 포함), ruff 통과, `claude plugin validate` 통과. **아직 어떤 환경에도 설치하지 않았다.** 라이선스는 정하지 않았다.

### 다음 할 일 (추천 순서, 사용자 최종 확정 전)

1. dev-guard를 Code_Agent 프로젝트에만 적용해 실사용 테스트(전역 설치 없이 dev-guard venv 절대 경로 사용).
2. dev-guard 2단계: 작업 종료 전 테스트 강제(Stop 게이트) → 언어별 메모리·CPU 측정 → 최적화 루프.
3. Code_Agent 평가: 프롬프트 예시 수정, 과제 확대(UNBORN, `PatchStore.propose` base binding 등), qwen3-8b·Devstral 비교, ca-001/002 실제 수정 반영.
4. 설계서 `effective_status` 규칙 수정 후 docs 동기화.
5. 라이선스는 사업화 방향이 정해질 때까지 보류.

## 2026-09-14 방향 기록: Ponytail/Potpie 장점 추출, 측정 도구, 자동 측정 실행기

- 사용자 요청으로 기록. 외부 도구를 통째로 의존하지 않고 장점만 우리 구조에 맞게 넣는 방향이다. 구현 미착수, 문서만 갱신했다. 현재 `profile/optimize`는 `CAPABILITY_NOT_AVAILABLE`이고 sandbox 실행 backend가 없으므로 아래 측정은 M07 단계 계획이다.

### Ponytail에서 가져올 것 / 버릴 것

- 가져올 것:
  - 판단 사다리(필요성 → 기존 코드 재사용 → 표준 라이브러리 → 설치된 의존성 → 최소 구현). patch proposal에 "선택한 단계와 이유" 필드로 남긴다.
  - 버그는 원인에서 수정: 수정 함수의 호출처를 모두 확인하고 공용 함수를 한 번 수정.
  - 줄이지 않는 항목: 신뢰 경계 입력 검증, 데이터 손실 방지, 보안.
  - `ponytail:` 주석(의도적 단순화의 한계·개선 경로)과 부채 장부.
  - 비자명 로직에는 실행 가능한 검사 1개를 남긴다.
- 버릴 것: 프롬프트만으로 강제하는 방식. 작은 모델은 무시하므로 추가 줄 수·새 의존성·새 파일 수를 자동 검사로 강제한다.

### Potpie에서 가져올 것 / 버릴 것

- 가져올 것:
  - 코드 외 지식(결정사항, 과거 버그·원인, 팀 규칙, 변경 이력). LSP로 얻을 수 없는 정보.
  - 작업 전 맥락 조회(`potpie resolve "<task>"`).
  - 서버 요약 없이 근거만 반환하는 방식(설계의 Evidence Priority와 일치).
  - 지식 기록 시 propose → verify → commit 절차.
  - 규칙/구조/이력/버그 차원 + 방해 데이터를 포함한 평가 방식.
- 버릴 것: 외부 연동·로그인(Local-Only 충돌), 무거운 의존성, Python >=3.12 요구.
- 순서: 재구현부터 하지 않는다. Potpie를 별도 CLI로 붙여 평가 세트로 효과를 측정한 뒤, 효과가 확인된 기능만 SQLite 기반으로 경량 구현한다.

### 메모리·성능 측정 도구

| 대상 | 도구 | 보여주는 것 |
|---|---|---|
| Python 할당 | `tracemalloc` | 최대 사용량, 할당 상위 N줄(`statistics("lineno")`), 수정 전후 비교(`snapshot.compare_to`) |
| Python 네이티브 포함 | memray (Linux) | C 확장 포함 할당 flame graph |
| 줄 단위 CPU+메모리 | Scalene | 줄별 CPU·메모리 |
| 프로세스 전체 | `ru_maxrss`, sandbox cgroup `memory.peak` | 실제 최대 사용량, OOM 여부 |
| 누수 의심 | `gc` 객체 타입별 개수 | 반복 실행 시 증가하는 타입 |
| Java(Spring) | JFR, `-Xlog:gc`, heap dump + MAT | 할당 위치, GC 부담, 힙 점유 |

- 결과는 JSON 보고서(최대 사용량, 할당 상위 위치, 기준선 대비 증가율)로 artifact에 저장하고 모델에 전달한다. 파일 경로가 포함되므로 M08 분류를 적용한다.

### 언제 무엇을 실행하나

| 시점 | 실행 | 이유 |
|---|---|---|
| 매 수정 루프 | tracemalloc 최대 사용량 + 상위 N줄, cgroup `memory.peak`/OOM | 가볍고 권한 불필요, cgroup은 sandbox 제한으로 비용 거의 없음 |
| 메모리 한도 초과 시 | `compare_to` 전후 비교, gc 타입별 개수 | 원인 위치를 좁혀 피드백 |
| `kh profile` / `kh optimize` | memray, Scalene, py-spy | 무겁고 일부 ptrace 필요 → 설계 21절 `profiling-ptrace` 전용 sandbox |
| 대상 저장소가 Java일 때 | JFR, GC 로그, heap dump | 현재 code-agent는 Python(pytest 템플릿)만 지원 |

- 측정 도구는 sandbox 이미지에 미리 포함한다(`--network=none`이라 실행 중 설치 불가).
- memray는 Linux 전용이므로 WSL/Linux 환경 확보가 선행 조건이다.
- 현재 code-agent 자체 개발 시에는 sandbox 없이 pytest에 메모리 테스트(예: 스캐너 증가율)를 바로 넣을 수 있다.

### 자동 측정 실행기 구조

- 측정 분리는 모델이 아니라 trusted 실행기가 매 루프 강제한다.
  1. 1차: pytest(측정 도구 없음) → 기능 통과 여부 + 실행 시간.
  2. 2차: pytest + 메모리 측정기 → 메모리 한도 테스트만 실행 → JSON 보고서.
  3. trusted 한도와 비교 → 초과 시 할당 상위 N줄을 모델에 전달 → 재수정.
- `sandbox/policy.py`의 `python-pytest-v1` 옆에 측정용 템플릿(예: `python-pytest-memory-v1`)을 추가한다. 측정기는 저장소 밖 trusted 경로에서 `-p`로 로드하며, 기존 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`로 저장소 플러그인의 개입을 막는다.
- 모델 몫: 한도와 이전 측정 결과를 문맥으로 받아 메모리를 고려한 수정을 시도한다. 준수는 보장되지 않으며 최종 판정은 2차 측정 게이트가 한다.
- 모델 금지: 제품 코드에 tracemalloc 등 측정 코드 삽입(측정은 실행기가 외부에서 부착), 메모리 한도·한도 테스트 수정(trusted 설정에만 존재, 수정 patch 차단).

### 그 밖의 고려 사항

- 품질·안정성: CPU·시간 프로파일(cProfile, py-spy, 증가율), 리소스 누수(fd, 스레드, DB 연결, 임시 파일, 좀비 프로세스), 동시성·TOCTOU·SQLite 잠금, 보안 정적 분석(ruff `S`, semgrep 로컬 규칙, 비밀정보 스캐너 보강 — 현재 정규식 4개), 의존성 공급망(lock 파일, 오프라인 OSV 미러, 라이선스).
- 루프 운영:
  - 실패 원인 분류(검색 실패/형식 오류/로직 오류/테스트 환경)를 기록해 개선할 부품을 판단한다. 최우선 권장.
  - 반복별 시간·토큰·재시도·결과 기록을 평가 지표로 사용.
  - 재현성: 모델 버전 고정, temperature 0, 환경 fingerprint.
  - GPU 경합: 블로그 RAG와 code-agent가 같은 LM Studio/A4000을 공유하므로 작업 대기열 또는 모델 분리가 필요하다.
  - 사용자 확인 화면: diff 보기, 변경 이유, 되돌리기.

## 2026-09-14 방향 기록: 코드 작성 흐름과 측정 기반 검사 루프

- 사용자 요청으로 기록. 개발 중(Claude/Codex 등)과 제품 내 로컬 모델 수정 루프에 공통 적용할 흐름이다. 구현 미착수, 문서만 갱신했다.
- 전제: 의존성 파악과 Ponytail은 호출처 파손·중복·비대화를 막지만, 이번 리뷰 결함(검사 누락, 분기 누락, 예외 상황 미고려)은 의존성/길이 문제가 아니었고 Ponytail 방식 코드와 129개 테스트 통과 상태에서 발견됐다. 따라서 실패 테스트 선행과 독립 검증이 필요하다. 현재 `impact`는 import 이름 매칭 수준이고 Potpie는 미연결이므로 정확한 의존성 파악에는 LSP 보강이 필요하다.

### 작업 흐름 (변경 단위마다)

1. 의존성 파악: Potpie로 넓은 관련성, LSP(pyright/jedi)로 정확한 정의·참조·호출처.
2. 실패 테스트 선행: 원하는 동작과 메모리/시간 한도를 먼저 테스트로 작성하고 수정 전 실패를 확인.
3. Ponytail로 최소 구현.
4. 테스트 + 측정: pytest, tracemalloc/프로세스 메모리, 필요 시 benchmark.
5. 독립 리뷰: 생성 과정과 다른 관점(별도 세션/모델)에서 diff 검토.

### 메모리·힙 검사 루프 조건

- 원칙: 메모리는 코드 읽기로 "고려"하지 않고 측정으로 판정한다(M07 근거 기반 측정). 읽기로 잡을 수 있는 것은 전체 적재·무한 증가 같은 명백한 패턴까지다.
- 루프: 구현 → 기능 테스트 + 메모리 테스트 → 실패 시 측정 결과 전달 → 수정 → 최대 N회 반복.
- 필수 조건:
  1. 한도는 모델이 변경 불가: 한도 값은 저장소 밖 trusted 설정에서 주입하고, 한도 테스트를 수정·삭제·skip하는 patch는 Test Selection Integrity 위반으로 차단한다.
  2. 입력 크기 고정 + 증가율 검사: 작은 fixture만으로 판정하지 않는다. 예: 입력 10배에서 peak가 정해진 배수(예: 3배) 이내인지 확인해 전체 메모리 적재 구조를 탐지한다.
  3. 측정 대상 구분: tracemalloc은 Python 할당만 측정한다. 프로세스 전체는 `ru_maxrss` 또는 sandbox cgroup `memory.peak`, sandbox `--memory` 초과 OOM kill은 FAIL. Java(Spring)는 `-Xmx` 제한 + GC 로그, 필요 시 heap dump.
  4. 흔들림 처리: 3회 중앙값, 허용 오차(예: 10%), 기능 테스트와 분리 실행(tracemalloc 오버헤드).
  5. 피드백 내용: 실패 여부만이 아니라 `tracemalloc.take_snapshot().statistics("lineno")[:10]` 상위 할당 위치를 모델에 전달한다.
  6. 종료 조건: 기능 테스트와 메모리 테스트가 모두 통과해야 성공(기능을 깨서 메모리를 줄이는 경우 차단). N회 내 개선이 없으면 중단하고 `INCONCLUSIVE`로 기록한다.
- 첫 적용 후보: `repository/snapshot.py` 스캐너는 모든 `.py` 내용을 `SourceFile.content`로 메모리에 보관하므로 증가율 테스트 대상으로 적합하다.

### 추가 검사 후보 (이번 리뷰 결함 유형 대응 우선)

1. 요구사항 ID ↔ 테스트 매핑: 설계의 테스트 ID(M01-UT-001, M02-CTX-001 등)를 테스트에 표시하고 매핑이 없는 불변조건을 목록화한다. "검사 줄 자체가 없는" 결함(base binding, `head_state`)을 찾는 가장 직접적인 방법. 현재 테스트에는 요구사항 ID 표시가 없다.
2. Property-based 테스트(hypothesis): `refs.py` packed-refs 파서, `core/canonical.py` 경로 인코딩, `patch/canonical.py` candidate 파서 등 파서·정규화 코드의 경계 입력 탐색.
3. 변경 코드 대상 mutation testing(mutmut 등): AI 생성 테스트가 코드를 실제로 검증하는지 확인. 느리므로 변경된 함수에만 적용.
4. 리소스 누수 검사: `-W error::ResourceWarning`, 실행 전후 열린 fd 수 비교(openat2 fd, SQLite 연결, 예외 경로 포함).
5. 정적 게이트: 현재 ruff select는 `E,F,I,UP,B`로 보안 규칙 `S`가 없고 타입 검사기가 없다. ruff `S` 추가 + pyright(또는 mypy) 도입 후보.
6. 시간 한도·증가율 테스트: 메모리와 같은 방식(고정 입력, 증가율, 중앙값)으로 CPU/실행 시간 검사.
7. 변경 줄 커버리지(diff-cover 등): 새 코드가 테스트에서 실제로 실행되는지 확인.
8. 장애 주입: DB 쓰기 실패(기존 trigger 방식 확장), 쓰기 도중 프로세스 종료 후 재시작 정합성.

### 재개 순서 (2026-09-14 기준, 아래 "오늘 종료 시점 요약"의 "다음 시작점"보다 우선)

1. 코드 리뷰 선행 수정 3건(`PatchStore.propose` base binding, 등록 저장소 삭제 시 정책 로드 실패, 정상 브랜치 `head_state`) + 각 회귀 테스트.
2. 같은 시점에 부담이 작은 품질 기준 도입: 추가 검사 후보 1번(요구사항 ID ↔ 테스트 매핑)과 5번(ruff `S` 규칙, pyright/mypy). 이후 모든 작업의 기준이 된다.
3. Safe Git object/index adapter(기존 1단계).
- 병행 확인: WSL/Linux 실행 환경 확보. Linux 전용 보안 코드(openat2, 스캐너, FileArtifacts, `require_linux_store`, `load_policy`)는 아직 실행 검증이 없고, sandbox·cgroup 메모리 측정 루프도 Linux/docker가 필요하다. 이 환경이 막히면 위 흐름의 측정 단계가 진행되지 않는다.
- 판단 기준: 이 흐름은 개발 품질(Claude/Codex로 code-agent를 만드는 과정)을 높이는 기준이다. 제품이 기업용 수준인지는 별도로 평가 세트(로컬 단독/+Potpie/+Ponytail/+둘 다/상한 모델) 성공률로 판단하며, 측정 전 달성으로 기록하지 않는다.

## 2026-09-14 코드 리뷰 결과: Safe Git adapter 착수 전 선행 수정 항목

- 사용자 요청으로 기록. 이 문서에 "완료"로 기록된 범위만 기준으로 code-agent를 읽기 전용 리뷰했다. 코드 수정은 하지 않았다.
- 테스트 재확인(2026-09-14): 129 passed / Linux-only 5 skipped. 이 PC에서 기본 설정으로 실행하면 `%TEMP%\pytest-of-<user>` 접근 권한 오류로 45 errors가 나며, `--basetemp`를 다른 폴더로 지정하면 전부 통과한다. 코드 결함이 아닌 환경 문제다.
- 주의: 아래 결함은 기존 129개 테스트를 모두 통과한 상태에서 발견됐다. 테스트가 코드와 같은 생성 과정에서 나와 일관성은 확인하지만 정확성은 보장하지 못한다.

### 완료 범위 안의 결함 (Safe Git adapter 전에 먼저 수정)

| 우선 | 문제 | 위치 |
|---|---|---|
| 높음 | `PatchStore.propose()`가 임의 dict proposal을 받고, 인자 `base_commit`·`source_snapshot_hash`·`intent_id`·repository와 proposal 내부 base의 일치를 검사하지 않는다. "base-bound proposal 저장 완료" 기록과 불일치. `CanonicalProposal`을 받아 base 값을 거기서 도출하는 방향. | `src/kh_agent/store/patches.py:74-186` |
| 높음 | 정책 파일이 있으면 `load_policy`가 등록된 모든 저장소를 `resolve(strict=True)`하므로, 등록 저장소 하나가 삭제·이동되면 다른 저장소 명령까지 `INVALID_INPUT_OR_ENVIRONMENT`로 실패한다. 이 로드는 identity/ACL 검사보다 먼저 실행된다. | `src/kh_agent/cli/app.py:68-77`, `src/kh_agent/security/policy.py:142` |
| 중간 | 정상 브랜치 HEAD도 `head_state`가 `UNRESOLVED`로 남는다(`NORMAL` 설정 없음). 설계 12.4.2의 UNRESOLVED 의미(손상/검사 실패)와 다르고 정상·unborn·ref 없음을 구분할 수 없다. 정상 경우 assert 테스트 없음. 다음 Safe Git 단계가 이 값을 이어받는다. | `src/kh_agent/repository/metadata.py:35-56` |
| 중간 | `impact`가 파일 경로를 그대로 모듈명으로 써서 `src/` 레이아웃(`src.pkg.mod`)에서 후보 0개, `from pkg import mod`는 `pkg`만 기록해 누락. | `src/kh_agent/analysis/python_graph.py:82-85,165` |
| 중간 | 스캐너가 권한 없는 파일 하나에 전체 실패하고, 비 Python 파일까지 읽고 해시해 16MB 한도에 합산한다. 설계 12.6.3의 PARTIAL/BLOCKED 판정 대신 전체 실패. | `src/kh_agent/repository/snapshot.py:152-193` |
| 낮음 | `final_diff_hash`와 verification plan이 audit 이벤트에 없어 재시작 검증이 이벤트만으로 해당 값을 복원·대조할 수 없다. | `src/kh_agent/store/patches.py:271-276` |

- 권장: 위 표의 높음 2건과 `head_state`를 먼저 수정하고, 각 수정에 회귀 테스트(불일치 base 거부, 삭제된 등록 저장소, 정상 브랜치 `NORMAL`)를 추가한 뒤 Safe Git object/index adapter로 진행한다.

### 완료된 코드지만 해당 단계에서 반영할 항목

- `VerificationReadiness`의 risk/plan 참조가 저장되지 않아 `finish_verification`의 policy basis와 대조 불가(`patches.py:245-321`). 참조 저장은 지금 가능, 실제 gate 연결은 2~4단계.
- sandbox pytest argv(`src/kh_agent/sandbox/policy.py:54-71`), 3단계 backend 구현 시 필수 수정: `python -I`는 `-E`를 포함해 `PYTHONDONTWRITEBYTECODE` 환경변수가 무시되고 cwd가 sys.path에 없어 flat-layout 프로젝트가 ImportError로 거짓 FAIL 가능. `-c /trusted/pytest.ini`로 rootdir이 `/trusted`가 됨. WSL2 기본 커널에서 AppArmor 옵션으로 docker 실행 실패 가능(확인 필요).
- `NOT_APPLICABLE`이 비어 있지 않은 참조 문자열만으로 통과(`src/kh_agent/core/lifecycle.py:55`). M07 self-exemption 금지는 4단계에서 강제.

### 결함으로 보지 않는 항목 (기존 남은 작업과 동일)

- 로컬 `permissions` 테이블이 ACL 원천인 점은 설계 11.8(Spring이 원천)과 다르지만 6단계 Spring 연동 항목이다. 설계 문서에 임시 구조임을 명시할 필요가 있다.
- dirty/index/COMPLETE, 실제 sandbox·apply, Linux 테스트 5개 미실행, dist 재빌드는 기존 1·3·5·7단계 항목이다.
- DB 컬럼명(`shared_git_identity_key` 등), CLI 종료 코드(설계 11.13), `kh history` 보호 결과 필터링은 해당 단계에서 설계와 맞춘다.
- blogProject(Spring/Next/FastAPI) 발견 사항(이미지 decode 메모리 고갈, 공개 RAG API 제한·timeout 부재, 게시글-벡터 트랜잭션 불일치, RAG fail-open)은 기존 앱 문제로 현재 작업 범위 밖이다.

## 2026-09-14 방향 기록: Potpie/Ponytail 보완 부품과 적용 순서

- 사용자 요청으로 기록. 목표는 작은 로컬 모델이 못하는 부분을 모델 밖의 결정적(trusted) 코드로 보완하는 것이다. 구현 완료나 요구사항 변경이 아니며 기존 안전 검사를 생략하는 근거가 아니다. 이번에는 문서만 갱신했고 코드·테스트는 변경하지 않았다.
- 확인한 근거:
  - Ponytail은 프롬프트 규칙이다. 자체 로컬 벤치마크(`Tools/ponytail/benchmarks/results/2026-06-15-llama3.2-local.md`)에서 llama3.2 3B는 코드량 감소가 오차 범위 안이었고 시간은 10~15% 느렸다. 작은 로컬 모델에서의 효과는 측정 전 가정하지 않는다.
  - Potpie는 코드·이력·결정 맥락 그래프다. 벤치마크(`Tools/potpie/docs/context-graph/bench-plan.md`)는 그래프 품질을 측정하며 LLM/코드 수정 성공률은 비목표다. 결과는 근거 묶음이고 판단은 모델 몫이다.
  - Potpie는 Python >=3.12 요구, code-agent는 3.11이므로 라이브러리 import가 아닌 별도 CLI/데몬 연동이 필요하다. 텔레메트리는 opt-in 기본 비활성이나 GitHub/Linear 연동·로그인·reconciliation LLM provider의 외부 통신 여부는 검증이 필요하다.
  - 현재 LM Studio 로드 설정은 `--context-length 8192`(`blogProject/blogProject-main/start-blog.ps1:82`)로, Potpie 근거 + 코드 + 규칙 + 테스트 출력을 담기 부족하다.
- 부품별 약점:
  - 로컬 모델: 추론·수정 능력 한계, 문맥 8K, diff 형식 오류.
  - Potpie: 넓은 관련성은 제공하나 정확한 호출 관계가 약하고 결과가 길며 검증하지 않는다.
  - Ponytail: 강제력이 없어 작은 모델이 무시할 수 있고 정확성을 보장하지 않는다.
  - code-agent: 테스트가 코드와 같은 생성 과정에서 나오며 영향 분석이 import 이름 매칭 수준이다.
- 보완 부품 후보(권장 순서):
  1. 실행 피드백 루프(직접 구현): 수정 → sandbox 테스트 → 실패 요약 → 최대 N회 재수정. `sandbox/policy.py` pytest 계획을 실행하는 최소 러너부터.
  2. 수정 형식 전환 + 출력 형식 강제(직접 구현): 현재 `patch/canonical.py`는 파일 전체 content를 받는다. 모델은 search/replace 또는 함수 단위 교체만 출력하고 trusted 코드가 canonical 전체 content로 변환한다. LM Studio/llama.cpp 구조화 출력(JSON schema/grammar)으로 형식 오류를 차단한다.
  3. 독립 검증(직접 구현): fail-to-pass(수정 전 실패·후 통과) + pass-to-pass(기존 테스트 유지) + ruff/pyright/컴파일 검사. 처음부터 통과하는 생성 테스트를 근거로 인정하지 않는다.
  4. 다중 후보 + 테스트 선택(직접 구현): 3~5개 패치 생성 후 통과한 것 중 최소 diff 선택. Ponytail을 프롬프트가 아닌 선택 기준으로 사용. 비용은 시간.
  5. 문맥 패커(직접 구현): Potpie 결과 + LSP 참조 + 대상 코드를 우선순위·토큰 예산으로 압축, 시그니처 요약(repo map 방식), 로컬 reranker로 Potpie 결과 재정렬(BGE-M3 환경 재사용).
  6. 정확한 코드 탐색(도입): jedi/pyright 기반 정의·참조·호출처. Potpie는 넓은 관련성, LSP는 정확한 관계로 역할 분리. `impact`의 import 이름 매칭 대체 후보.
  7. Ponytail 강제 검사(직접 구현, Post-Apply Guardrail): 추가 줄 수 상한, 새 의존성 감지, 복잡도 증가 검사. 모델의 지시 준수와 무관하게 측정으로 거절.
  8. 실패 기억(Potpie 활용): 실패 원인·수정 패턴을 `potpie record`로 저장해 이후 맥락에 재주입.
  9. 모델 역할 분리(설정): 계획·검색 요약은 소형 모델, 수정은 16GB에 맞는 양자화 코딩 특화 모델. 평가 세트로 선택.
- 넣지 않을 것: 복잡한 멀티 에이전트 프레임워크. 작은 모델에서 단계가 늘면 오류가 누적되므로 판단은 결정적 코드에 둔다.
- 평가 방식: 실제 버그 사례 20~50개로 로컬 단독 / +Potpie / +Ponytail / +둘 다 / 참고용 상한 모델을 같은 조건에서 비교한다. 부품은 하나씩 켜고 끄며 성공률·회귀·재시도·시간을 기록하고, 효과가 없으면 제거한다. 1~3번까지가 "모델 → 수정 → 테스트 → 재수정"이 도는 최소 제품 기준이다.

## 2026-09-14 방향 결정: 현재 Local-Only 유지

- 사용자 결정: 현재 v1.10은 기존 M08의 Local-Only 정책을 유지한다. 외부 LLM/embedding/web search 허용 기능을 이번 구현 범위에 추가하지 않는다.
- Local-Only는 현재 제품의 정책과 완료 목표다. 실제 전체 runtime의 외부 통신 차단 검증이 완료됐다는 뜻은 아니다. 모델 주소 검증, offline 모델 로딩, 앱/모델/테스트 프로세스의 egress 강제 및 실패 시 실행 차단을 구현·검증해야 한다.
- 후속 확장 방향: 사용자가 프로젝트/파일/데이터별 보호 등급을 지정하고, 명시적으로 외부 전송을 허용한 데이터만 지정된 외부 서비스에서 처리하는 정책을 검토한다. 보호 대상은 로컬 또는 허가된 사내 환경에서만 처리한다.
- 후속 정책은 원본뿐 아니라 파생 프롬프트·코드 조각·답변·패치·로그에도 보호 등급을 전파해야 한다. 보호/허용 데이터가 섞이거나 분류가 불명확하면 외부 전송을 차단한다. 전송 대상·범위·현재 권한·명시적 승인·감사 기록을 검증하며, 로컬 적용 승인을 외부 전송 승인으로 간주하지 않는다.
- 이 확장은 검토 후보이며 구현 완료나 현재 외부 전송 허가가 아니다. 기존 freeze 요구 문서는 변경하지 않았다.
- 제품 목표는 범용 코딩 어시스턴트로 유지한다. 구현 검증은 작은 Python 저장소의 수정→격리 테스트→diff 검토→승인·적용 흐름부터 증명하고 지원 범위를 넓히는 방향이다. 이 순서는 제안이며 전체 요구사항을 삭제하거나 완료 처리하지 않는다.
- 이번 요청에서는 방향 기록만 갱신했다. 코드 구현 및 테스트를 재개하지 않았으며 마지막 결과는 129 passed / Linux-only 5 skipped다.

## 오늘 종료 시점 요약

### 2026-09-14 추가 기록: 코딩 품질을 개발 중간부터 검증

- 사용자 요청으로 기록: 현재 구조는 안전한 변경 관리·검증의 기반이며, 높은 코드 생성/수정 품질을 증명한 상태가 아니다. 129개 테스트 통과는 기반 구현의 회귀 검증이지 어시스턴트의 실제 수정 성공률이 아니다.
- 품질의 핵심 요소는 사용할 로컬 모델의 문제 해결 능력, 관련 코드·호출 관계·제약의 정확한 맥락 제공, 테스트/프로파일링 결과에 따른 재수정이다. Local-Only 정책은 유지한다.
- 전체 기능 완성 뒤로 품질 평가를 미루지 않는다. 필요한 안전한 실행 경계를 갖춘 뒤, 작은 실제 저장소의 버그 수정과 메모리 최적화 사례로 모델→변경→격리 검증→재수정 흐름을 개발 중간부터 평가한다.
- 같은 작업·실행 조건에서 수정 성공 여부, 기존 기능 회귀, 재시도 횟수, 처리 시간 및 최적화 전후 메모리/실행 시간을 기록한다. 모델/검색/재수정 방식을 바꿀 때 같은 평가 사례로 비교하고, 평가용 테스트를 약화해 성공으로 만들지 않는다.
- 결과에 따라 모델·맥락 검색·재시도 방식을 조정한다. 높은 품질이나 기업 도입 수준을 측정 전에 단정하지 않는다. 현재 모델 연결 및 실제 수정 품질 평가는 미완료다.
- 이 기록은 개발 방향 보완이며 전체 요구사항이나 안전 검사를 생략하는 승인이 아니다. 이번에는 문서만 갱신했고 코드 구현·테스트를 재개하지 않았다.

- 사용자 요청으로 오늘 작업을 종료한다. 다음 사용자 재개 요청 전에는 추가 구현하지 않는다.
- 현재 위치: 공통 저장·권한·정적 분석·패치/위험/명령/정책 기반 코드 구현 후, M02 Git 참조 조회 보강까지 완료했다. 실제 코드 수정→격리 실행→검증→승인→적용의 전체 흐름은 아직 미완료다.
- 마지막 검증: 129 passed / Linux 전용 5 skipped, Ruff lint/format 통과. 오늘 종료 기록에서는 코드 변경이나 테스트 재실행을 하지 않았다.
- 남은 작업은 아래 **큰 묶음 7단계**다. 설계 모듈의 완료 개수나 동일한 작업량을 뜻하지 않으며 각 단계는 여러 번의 구현으로 나눌 수 있다. 정확한 완료율·남은 일수는 아직 산정하지 않는다.

| 남은 순서 | 단계 | 완료 판단 기준 |
|---|---|---|
| 1 | 안전한 Git 객체·인덱스·소스 검사 | 허가된 객체 출처, HEAD/index/dirty/freshness 검사와 COMPLETE source 기준 검증 |
| 2 | 위험 근거·정책·실행 전후 검사 연결 | 실제 evidence와 정책 버전/감사 기록을 위험 판단 및 guardrail에 연결 |
| 3 | 실제 패치 생성·격리 실행 | 안전한 worktree 변경 및 rootless sandbox 실행·격리 증명 |
| 4 | 테스트·성능 측정·검증 확정 | 실제 runtime 결과와 소스 기준을 verification에 연결 |
| 5 | 사용자 승인·적용·복구 | 승인한 변경만 적용하고 lock/중단 복구/postimage 검증 |
| 6 | 기존 서비스·화면·로컬 AI 연결 | Spring 인증/ACL, Web 조회, Local LLM/Potpie 연동 검증 |
| 7 | Linux 및 전체 인수 검증 | Linux 전용 테스트와 M11 전체 흐름 검증, 최신 배포 산출물 빌드 |

- 다음 시작점: 1단계의 Safe Git object/index adapter. `src/kh_agent/repository/metadata.py`, `refs.py`, `identity.py` 및 `tests/test_repository_metadata.py`를 확인한 뒤 격리된 administrative copy와 고정 Git 명령의 경계부터 구현한다. 경로는 `blogProject/blogProject-main/code-agent/` 기준이다.
- 재개할 때 이 파일과 `RESTART_HANDOFF.md`를 먼저 읽는다. Windows 개발은 계속할 수 있고 WSL 설치를 반복하지 않는다. 기존 `dist`는 최신 참조 조회 변경 이전 빌드다.

## 사용자 요청

- Knowledge Hub Code Intelligence v1.10 구현을 계속 진행한다.
- WSL 초기화가 응답하지 않아도 코드 작성을 중단하지 않는다. 현재 Windows 작업 폴더에서 개발하고 Linux 실행 검증을 별도로 남긴다.
- 사용량이 25% 남았을 때 진행사항을 기록한다. 현재 세션에는 계정 잔여 사용량 조회 도구가 없어 자동 임계 감지를 약속하지 않는다. 사용자가 잔여율을 알려주면 그 시점에 다시 기록한다. 중간 기록도 수시로 갱신한다.

## 구현 위치와 환경

- 코드: `blogProject/blogProject-main/code-agent/`
- Python 3.11.16, 프로젝트 `.venv` 구성 완료.
- 설치된 개발 의존성: Typer 0.27.2, pytest 9.1.1, Ruff 0.16.7, PyYAML 6.0.3. `uv.lock` 생성 완료.
- WSL 2.7.14 / Ubuntu Running(WSL2) 등록은 확인했으나 Linux 명령 응답은 여전히 미확인. 설치를 반복하지 않는다.
- 기존 Spring/Next.js/FastAPI 제품 코드는 아직 변경하지 않았다.
- 현재 디렉터리와 앱 폴더는 Git checkout이 아니다. commit/PR은 생성하지 않았다.
- 작업 폴더 내부에는 AGENTS.md가 없고 상위 사용자 홈의 `AGENTS.md`를 추가 확인했다. Potpie-informed Ponytail/full workflow 적용. Potpie 실행 파일은 PATH 및 uv tool bin에서 발견되지 않아 로컬 source/test 도구를 사용했다. 사용자 승인 없이 sub-agent를 생성하지 않는다.

## 구현 및 확인된 내용

- 공통 domain: typed UUID4 ID, positive revision, versioned deterministic JSON/SHA-256, filesystem path byte encoding, 상태 전이와 검증 readiness.
- M09 기반: SQLite WAL/FULL/foreign keys, schema version, append-only audit trigger, 상태+이벤트 원자적 transaction, idempotency 충돌 처리.
- 패치 proposal/revision 저장, 검증 plan/result/basis 저장, 필수 check 누락·소스 변동·artifact 변조 차단, 재시작 시 audit/state integrity 검사.
- Linux 파일 artifact backend: owner-only, no-follow, fsync file/rename/directory, hash 검증, orphan 조회. 민감 artifact 암호화 키 미연결이면 차단.
- M01 기반: Linux UID mapping(환경변수 사용자명 불신), invalid session의 OS identity fallback 금지, 등록된 canonical repository/root identity, current ACL, 권한 변경 audit.
- CLI: doctor/init/repo register/access add-user·grant·revoke/status/history/policy-check.
- Python static explain/impact: AST로 정의/import/call expression 추출, import-name candidate 표시, graph hash 및 DB/audit 저장.
- Linux source scanner: openat2 NO_SYMLINKS/BENEATH/NO_XDEV, mount·nested repo·symlink·hardlink·민감 파일 제외, quota, read consistency 검사.
- 소스 snapshot/graph는 PARTIAL로 명시. Git index/object/dirty state 및 point-in-time 전체 일관성은 아직 검증하지 못하므로 mutation authority로 사용하지 않는다.
- M05 regular-file canonical proposal: JSON 중복/authority 필드 거부, base-bound identity, create/modify/delete, sensitive/alias/parent conflict 차단, preimage 검사, pure preview, actual manifest 비교.
- M04 risk domain: versioned factor normalization/weights/threshold, integer ceiling 계산, missing evidence는 exact score=null 및 min/max interval, 보수적 upper-bound level, incomplete change set의 Final Risk 차단.
- M06 command domain: pytest structured request, fixed argv/environment, forged compiled command 거부, digest-pinned/offline/non-root/read-only Docker plan. 실제 runtime execution backend가 아니다.
- M08 YAML: SafeLoader 기반 strict duplicate/unknown/tag/anchor/alias 거부, input/depth/resource bound, 외부 owner-private 파일 로드. 예외/egress 허용 DSL은 아직 미지원.
- Python parser에 byte/token/AST node 한도를 추가했다. source text를 실행하거나 graph DB에 원문 저장하지 않는다.
- README, `config/policy.example.yaml`, `scripts/check-linux.sh`, dependency lock 작성 완료.
- 이전 단계 wheel 및 source distribution 빌드 성공. wheel 내부 SQL resource 및 새 DB bootstrap 확인 완료. 이번 참조 조회 변경은 소스에 반영했으며 기존 dist에는 아직 포함되지 않는다.

## 마지막 완료된 테스트

명령(프로젝트 code-agent 폴더):

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
.venv/Scripts/python.exe -m kh_agent doctor
```

- 129 passed, 5 skipped.
- Linux 전용 artifact/openat2/source scanner 실행 테스트 5개는 Windows라 skip. 통과로 간주하지 않는다.
- 마지막 완료된 lint/format 검사 통과.
- 테스트에는 MemoryArtifacts/test-only scanner/runtime injection이 사용된다. Windows 테스트 통과를 Linux 파일시스템·샌드박스 검증 완료로 오인하지 않는다.

## 현재 체크포인트

- 기존 106개 테스트에 Git 참조·읽기 일관성 회귀 테스트 23개를 추가했다.
- 2026-09-13 단계별 진행: loose ref 우선 / packed-refs fallback, SHA-1·SHA-256 선언 ID, peeled record 검사, 참조 경로·중복·4 MiB 한도 검사를 구현했다.
- 공통 metadata reader는 읽기 전후 fstat와 최종 경로 identity/크기/시간을 비교하며 hardlink/alias/special file을 차단한다. Linux O_NONBLOCK으로 FIFO open 대기를 방지한다.
- HEAD/ref 재조회로 변경과 없던 loose ref 생성을 감지한다. 원자적 repository snapshot, 객체 존재, dirty 상태를 증명하지 않는다. commit_sha/working_tree_dirty는 여전히 null, mutation_ready는 false다.
- 전체 테스트 및 lint/format을 확인했다. dist는 이전 단계 빌드이므로 최신 소스 배포 시 재빌드가 필요하다.
- 잔여 사용량 25% 아래에서도 재개할 수 있도록 매 단계 기록한다. 계정 잔여율은 직접 조회할 수 없다.

## 남은 주요 작업

1. M02 다음 단계: native Git을 격리된 administrative copy에서 고정 명령으로 실행하는 adapter와 object/index 검사. source config/hook/filter/외부 object store를 실행·참조하지 않도록 경계를 먼저 구현한다. packed object/object source authorization, dirty/index/materialization, freshness 및 COMPLETE source 기준은 미완료. 현재 metadata 참조 조회만 구현했으며 symbolic ref chain/reftable도 미지원이다.
2. M04 실제 evidence provider 및 M06 Pre/Post guardrail 통합, trusted policy 변경 audit/version lifecycle 보강.
3. M05 실제 안전한 worktree materialization/mutation, M06 rootless isolated backend와 runtime attestation.
4. M07 runtime test/profiling/benchmark, finalized verification 기준 연결.
5. Informed approval binding, 실제 apply/lock/durable intent/recovery 및 postimage 검증.
6. Spring 인증/ACL bridge와 Web query projection, Local LLM/Potpie 검증된 local-only 연동.
7. Linux 실행 테스트 및 M11 전체 acceptance. 문서 검증 86건을 제품 테스트 결과로 사용하지 않는다.

전체 v1.10 구현 완료 상태가 아니다. `modify/profile/optimize/verify/apply` CLI는 아직 CAPABILITY_NOT_AVAILABLE로 차단된다. DB 내부 persistence API가 있다고 실제 검증·승인·적용 기능이 완성된 것은 아니다.
