# Code Agent CLI

**Python 저장소의 코드 분석과 명시적 수정 검증을 지원하는 로컬 우선 보안 지향 코딩 에이전트 CLI**

[English](README.md) | [한국어](README.ko.md)

**상태:** 실험적 버전 v0.1.0 · **라이선스:** [Apache-2.0](LICENSE) · **개발자:** JongHyeok Jang ([@homilpat](https://github.com/homilpat))

Code Agent CLI는 Git 저장소 상태 확인, 로컬 사용자 권한, 감사 기록, Python 코드 분석, 로컬 LLM의 수정안 생성, 컨테이너 기반 검증을 연결하는 실험적 도구입니다. 핵심 설계 방향은 **분석 → 수정안 생성 → 검토 → 격리 검증 → 명시적 적용**입니다.

> **현재 범위:** Python 중심의 실험적 CLI입니다. 자율적인 다중 파일 수정 에이전트나 임의의 LLM 명령 실행을 완전히 격리하는 상용 보안 제품은 아닙니다.

## 프로젝트 배경

AI가 그럴듯한 코드를 생성했다고 해서 올바른 저장소와 파일 버전을 수정했는지, 필요한 권한을 확인했는지, 테스트 환경이 신뢰할 수 있는지까지 보장되지는 않습니다.

이 프로젝트는 코딩 에이전트의 작업을 **검증 가능한 절차**로 구성하는 것을 목표로 합니다. 등록된 Git 저장소와 사용자 권한을 확인하고, 변경과 검사 상태를 기록하며, 코드 수정안을 Rootless Podman 환경에서 테스트한 후 단일 파일 변경을 명시적으로 허용합니다.

기존 Knowledge Hub 모노레포에서 코드 에이전트 부분을 분리했습니다. 독립 CLI 실행에 Spring Boot, Next.js, MySQL, RAG 서비스는 필요하지 않습니다.

## 주요 기능 및 구현 상태

| 영역 | 현재 기능 | 상태 |
| --- | --- | --- |
| CLI 초기화 | `doctor`, `init`, 저장소 등록, 도움말 | 구현 |
| 인증·권한 | Linux UID 기반 로컬 사용자 식별, 저장소별 권한 부여·회수 | 구현 |
| Git 상태 검사 | HEAD, index, worktree 및 변경 상태 검증 | 구현 |
| 기록·저장소 | SQLite 기반 감사 메타데이터, 실행·검증 상태 | 구현 |
| Python 정적 분석 | AST 기반 `explain`, import 후보 `impact` | 부분 구현 |
| 시맨틱 분석 | Rootless Podman 안에서 Pyright 질의 | 환경 구성 필요 |
| 로컬 모델 연동 | 로컬 OpenAI 호환 모델을 통한 `modify` 수정안 생성 | 실험적 |
| 수정안 확인 | 원본 파일을 변경하지 않는 `preview-candidate` | 구현 |
| 수정안 테스트 | Rootless Podman에서 등록된 pytest 실행 | 실험적 |
| 단일 파일 적용 | 검토 해시·원본 상태·재검증을 요구하는 `apply-candidate` | 실험적 |
| 완전 자율 다중 파일 수정, 정식 승인 파이프라인, 웹 인증, 범용 최적화 | 제공하지 않음 | 미구현 |

`profile`, `optimize`, `verify`, `apply` 명령은 현재 **예약된 기능**입니다. 명령어가 도움말에 표시된다고 해서 전체 워크플로가 구현됐다는 의미는 아닙니다.

## 실행 환경

- Python **3.11 이상**, [uv](https://docs.astral.sh/uv/)
- **WSL2/Linux** 및 로컬 Linux **ext4/XFS/Btrfs** 파일시스템
- Git
- 격리된 테스트·Pyright 실행을 위한 **Rootless Podman**과 사전 준비된 이미지
- 모델 기반 `modify` 기능을 사용할 때만 로컬 OpenAI 호환 LLM 서버

네이티브 Windows에서는 개발·테스트 및 `doctor`는 가능하지만 **저장소 상태를 변경하거나 관리하는 주요 기능은 지원하지 않습니다**. Windows 드라이브를 WSL에 연결한 `/mnt/c`나 네트워크 드라이브에는 권한 데이터베이스를 저장하지 마세요.

## 설치 및 시작

PR #1이 병합되기 전에는 독립 CLI 브랜치를 선택해 복제합니다.

```bash
git clone --branch refactor/standalone-code-agent-cli https://github.com/homilpat/Code_Agent.git
cd Code_Agent
uv sync --extra dev --locked

uv run code-agent --help
uv run code-agent doctor
```

현재 GitHub 저장소가 비공개이므로 복제하려면 접근 권한이 필요합니다. 별도의 웹서비스 실행이나 클라우드 API 키 등록은 필요하지 않습니다.

### Git 저장소 등록 및 분석

지원되는 Linux/WSL2 환경에서:

```bash
uv run code-agent init
uv run code-agent repo register /home/user/projects/example
uv run code-agent status --repo /home/user/projects/example
uv run code-agent explain src/example.py --repo /home/user/projects/example
uv run code-agent impact src/example.py --repo /home/user/projects/example
uv run code-agent history --repo /home/user/projects/example
```

대상 Git 저장소는 실제로 존재해야 하며 보안 검사 조건을 충족하고 먼저 등록돼야 합니다. 신뢰 저장소는 대상 Git 저장소 **외부**에 위치해야 합니다. `explain`과 `impact`의 Python 파일 경로는 등록된 저장소 기준 상대 경로입니다.

### 로컬 AI 수정안 생성

로컬 OpenAI 호환 서버에 모델을 실행한 다음 모델 식별자와 Python 파일을 지정합니다.

```bash
uv run code-agent modify "반환값 오류를 수정해줘" \
  --target src/example.py \
  --model "$LOCAL_MODEL_ID" \
  --port 1234 \
  --repo /home/user/projects/example
```

`--image`와 `--test`를 지정하지 않으면 **수정안 미리보기**를 생성하며 원본을 자동 변경하지 않습니다. 이미지 옵션을 사용할 때는 최소 하나 이상의 테스트 경로를 함께 지정해야 합니다. 정확한 인수는 `uv run code-agent modify --help`를 참고하세요.

### 검증 및 명시적 적용

```bash
uv run code-agent preview-candidate --help
uv run code-agent verify-candidate --help
uv run code-agent apply-candidate --help
uv run code-agent semantic --help
```

실험적 단일 파일 적용에는 사용자가 검토한 수정안·원본·대상 상태 해시, 사전 구성된 컨테이너 이미지, 격리 환경의 새로운 테스트 실행 등이 필요합니다. **테스트 통과만으로 소프트웨어의 정확성과 안전성이 증명되지는 않습니다.**

## 보안 설계와 한계

- Linux 운영체제 사용자 식별자와 저장소별 ACL을 사용합니다.
- Git과 worktree 상태가 변경되거나 불완전하면 일부 변경 작업을 거부합니다.
- 로컬 SQLite에 감사 **메타데이터**를 기록하며 저장소 경로와 파일 권한을 제한합니다.
- Rootless Podman은 특정 테스트·시맨틱 분석 실행 경로를 격리합니다.
- 별도 `evals/` 평가 러너의 테스트는 **호스트에서 실행**되므로 제품 샌드박스의 보호를 받지 않습니다.
- 로컬 모델 서버를 사용하더라도 전달할 파일과 설정은 사용자가 검토해야 합니다.

**임의의 셸 명령을 자동 격리하거나 모든 비밀정보 유출을 방지한다고 보장하지 않습니다.** 보안 검증이 필요한 실제 시스템에서는 별도의 코드 감사와 운영 환경 통제가 필요합니다.

## 프로젝트 구조

```text
Code_Agent/
├── src/kh_agent/           # 핵심 CLI 엔진 (호환성을 위해 기존 import명 유지)
├── tests/                  # 단위·보안·통합 테스트
├── config/sandbox/         # Rootless Podman 이미지 정의
├── evals/                  # 독립 연구 평가 러너 및 과제
├── scripts/                # Linux 검증 스크립트
├── docs/                   # 마이그레이션 및 설계 문서
├── .github/workflows/      # CI
├── pyproject.toml
├── uv.lock
├── README.md
├── README.ko.md
├── LICENSE
├── NOTICE
└── CITATION.cff
```

배포 패키지명은 `code-agent-cli`, 권장 CLI 명령어는 `code-agent`입니다. 내부 Python import 경로 `kh_agent`는 기존 코드의 안전한 호환성을 위해 유지하며, `kh` 명령도 임시 호환 별칭으로 남아 있습니다.

## 테스트 및 재현

저장소 루트에서 실행합니다.

```bash
uv sync --extra dev --locked
uv run pytest -q
uv run python -m pytest -q evals/tests -p no:cacheprovider
uv run ruff check .
uv run ruff format --check src tests evals
```

GitHub Actions에서는 Rootless Podman 및 Pyright 통합 테스트도 실행합니다. 이전 검증 기록은 **통합 테스트 9개 통과**, **핵심 테스트 255개 통과·플랫폼별 1개 skip**, **평가 러너 테스트 32개 통과**, Ruff 검사 통과였습니다. 이는 **에이전트의 문제 해결 성공률이 아닌 소프트웨어 테스트 결과**입니다. 최신 상태는 [GitHub Actions](https://github.com/homilpat/Code_Agent/actions)에서 확인하세요.

### 연구 평가

`evals/`는 제품의 보안 경계와 분리된 **실험용 러너**입니다. 과거 Git 커밋에서 임시 작업 공간을 생성하고, 로컬 모델의 SEARCH/REPLACE 수정안을 적용하며, 숨김 테스트와 회귀 여부를 검사해 결과를 기록합니다.

```bash
uv run python -m evals.runner validate
uv run python -m evals.runner run --model YOUR_LOCAL_MODEL_ID --attempts 3
```

`run`에는 로컬 모델 서버가 필요합니다. 평가 테스트는 **호스트에서 실행**되므로 신뢰 가능한 과제만 사용해야 합니다. 현재 과제 규모는 작아 연구 결과를 일반화할 수 없습니다. 자세한 내용은 [evals/README.md](evals/README.md)를 확인하세요.

## 이전 버전 데이터 호환

신규 설치는 `~/.code-agent/db/code-agent.db`를 사용합니다. 기존 `~/.knowledge-hub`가 존재하면 해당 저장소와 `db/knowledge-hub.db`를 우선 사용할 수 있습니다. 사용자 데이터를 자동 복사하거나 삭제하지 않습니다. 다른 저장소를 지정하려면 전역 `--store` 옵션을 사용하세요. 자세한 내용은 [CLI 마이그레이션 안내](docs/CLI_MIGRATION.md)를 참고하세요.

## 향후 연구 방향

다음은 **현재 구현된 기능이 아닌 계획**입니다: 에이전트 보안 정책별 비교 실험, 평가 과제 확대, 작업 성공률과 보안 위반률의 정량 비교, 내부 `kh_agent` 패키지명 마이그레이션의 독립 검증.


## MCP 연동 (로컬 stdio)

기존 CLI 엔진을 **MCP를 지원하는 호스트 앱**에 연결할 수 있도록 별도의 stdio MCP 어댑터를 제공합니다. 저장소 상태, 감사 이력, Python 정적 분석, 영향 후보, 로컬 LLM 기반 **수정안 미리보기**를 도구로 노출합니다.

```bash
uv run --with 'mcp>=2,<3' python -m kh_agent.mcp_server
```

MCP SDK는 이 명령 실행 시에만 추가 설치되므로 기존 잠금 파일을 변경하지 않습니다. **Ollama·LM Studio에서 모델을 실행하는 것만으로 MCP 호스트가 되는 것은 아닙니다.** MCP 호환 에이전트·앱을 통해 연결해야 합니다. 임의 셸 명령 실행과 자동 코드 적용 도구는 제공하지 않습니다. [연동 안내](docs/MCP_INTEGRATION.md)를 참고하세요.

## 라이선스·연구 인용·저작권

Copyright © 2026 **JongHyeok Jang**. 이 프로젝트는 **[Apache License 2.0](LICENSE)**을 따릅니다. 라이선스 조건에 따라 상업적 사용·수정·재배포가 가능하지만, 필요한 저작권·라이선스 고지를 보존하고 수정한 파일에는 변경 사실을 표시해야 합니다. [NOTICE](NOTICE)를 참고하세요. 외부 의존성에는 각자의 라이선스가 적용됩니다.

학술 연구에서 활용한다면 [CITATION.cff](CITATION.cff)를 기준으로 **출처를 인용해 주세요**. 학술 인용은 권장사항이며 Apache 2.0의 추가 법적 의무가 아닙니다.

독립 CLI 브랜치에 부여한 라이선스가 과거 Git 이력에 남아 있는 Knowledge Hub 웹서비스 코드까지 **소급해서 재라이선스하는 것은 아닙니다**.
