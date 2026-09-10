# Knowledge Hub 종합 지식 블로그 운영 방법

이 문서는 로컬 개발 환경에서 블로그 전체 서비스를 실행하고 종료하는 방법을 설명합니다.

## 1. 구성 서비스

Docker Compose가 다음 서비스를 함께 실행합니다.

| 서비스 | 역할 | 기본 접속 주소 |
|---|---|---|
| Next.js | 블로그 웹 화면 | http://localhost:3000 |
| Spring Boot | 인증, 게시글, 이미지 API | http://localhost:8080 |
| FastAPI | AI/RAG 처리 | Docker 내부 통신 |
| MySQL | 사용자, 카테고리, 게시글 저장 | Docker 내부 통신 |
| Qdrant | RAG 벡터 저장 | Docker 내부 통신 |
| SearXNG | API 키 없는 웹 메타 검색 | Docker 내부 통신 |

포트는 루트의 `.env` 설정에 따라 달라질 수 있습니다.

## 2. 최초 실행 전 준비

1. Docker Desktop을 설치하고 실행합니다.
2. LM Studio를 사용하는 경우 Qwen3 8B와 Gemma 4 E4B 모델 및 로컬 API 서버를 먼저 실행합니다. `start-blog.ps1`을 사용하면 두 모델을 각각 `planner-model`, `answer-model` 식별자로 자동 로드합니다.
3. 프로젝트 루트에 `.env` 파일이 있는지 확인합니다.
4. `.env`의 비밀번호, JWT 비밀키, 포트 및 서비스 주소를 올바르게 설정합니다.

실제 `.env` 파일은 비밀정보를 포함하므로 Git에 올리지 않습니다. 설정 항목은 `.env.example`을 참고합니다.

## 3. 전체 서버 실행

PowerShell에서 다음 명령을 실행합니다.

```powershell
cd C:\Users\user\Desktop\blogProject
docker compose up -d --build
```

`--build`는 변경된 프론트엔드와 백엔드 코드를 다시 빌드합니다. 이미지 업로드 기능처럼 코드가 변경된 후에는 이 명령을 사용합니다.

실행 후 브라우저에서 다음 주소를 엽니다.

```text
http://localhost:3000
```

일반 질의의 `generation_mode` 기본값은 `auto`입니다. 최초 Planner가 질문을 직접 조회·비교·인과·절차·종합·판단 구조로 분석합니다. 직접 조회는 `qwen_direct`, 근거 종합이나 판단이 필요한 구조는 `hierarchical`로 선택됩니다. 평가 시에는 두 값을 명시해 자동 라우팅을 우회할 수 있습니다.

## 4. 상태 확인

```powershell
docker compose ps
```

모든 서비스의 상태가 `Up` 또는 `running`인지 확인합니다.

전체 로그를 실시간으로 확인하려면 다음 명령을 사용합니다.

```powershell
docker compose logs -f
```

특정 서비스 로그만 확인할 수도 있습니다.

```powershell
docker compose logs -f frontend-blog
docker compose logs -f backend-spring
docker compose logs -f rag-fastapi
docker compose logs -f mysql-db
docker compose logs -f vector-db
docker compose logs -f web-search
```

로그 화면은 `Ctrl+C`로 빠져나옵니다. 서비스 자체는 계속 실행됩니다.

## 5. 서버 종료와 재시작

컨테이너를 유지한 채 서비스를 멈춥니다.

```powershell
docker compose stop
```

멈춘 서비스를 다시 실행합니다.

```powershell
docker compose start
```

서비스를 재시작합니다.

```powershell
docker compose restart
```

컨테이너를 제거하며 종료하되 MySQL, Qdrant 및 업로드 이미지 볼륨은 보존합니다.

```powershell
docker compose down
```

다시 생성하고 실행하려면 다음 명령을 사용합니다.

```powershell
docker compose up -d --build
```

> `docker compose down -v`는 사용하지 마세요. `-v`를 붙이면 게시글 데이터, 벡터 데이터 및 업로드 이미지가 저장된 Docker 볼륨까지 삭제될 수 있습니다.

## 6. 코드 수정 후 적용

프론트엔드 또는 백엔드 코드를 수정한 후에는 다음 명령으로 다시 빌드합니다.

```powershell
docker compose up -d --build
```

특정 서비스만 다시 빌드하고 싶다면 다음과 같이 실행합니다.

```powershell
docker compose up -d --build frontend-blog
docker compose up -d --build backend-spring
```

## 7. 이미지 데이터 보관

업로드된 이미지는 `blog_uploads` Docker 볼륨에 저장됩니다. 컨테이너를 재시작하거나 `docker compose down`을 실행해도 이미지가 유지됩니다.

게시글을 삭제하면 다른 게시글이 사용하지 않는 해당 게시글의 이미지도 삭제됩니다. 게시글 수정 시 본문에서 제거한 이미지 역시 저장 완료 후 정리됩니다.

Docker 볼륨 목록 확인:

```powershell
docker volume ls
```

운영 데이터가 필요하다면 Docker 볼륨을 삭제하기 전에 반드시 별도로 백업합니다.

## 8. 자주 발생하는 문제

### `docker` 명령을 찾을 수 없는 경우

- Docker Desktop이 설치되어 있는지 확인합니다.
- Docker Desktop을 실행합니다.
- PowerShell을 닫고 새로 엽니다.
- `docker version` 명령으로 설치 상태를 확인합니다.

### Docker 엔진에 연결할 수 없는 경우

Docker Desktop 실행이 완전히 끝날 때까지 기다린 후 다시 실행합니다.

```powershell
docker compose up -d --build
```

### 웹 페이지가 열리지 않는 경우

```powershell
docker compose ps
docker compose logs --tail=100 frontend-blog
docker compose logs --tail=100 backend-spring
```

`.env`의 `FRONTEND_HOST_PORT`, `BACKEND_HOST_PORT`, `NEXT_PUBLIC_API_URL`, `CORS_ALLOWED_ORIGINS`도 확인합니다. 로컬에서는 `http://localhost:3000`과 `http://127.0.0.1:3000`을 모두 허용해야 두 주소 중 어느 것으로 접속해도 작성 API가 차단되지 않습니다.

### 이미지 업로드가 실패하는 경우

- 로그인 상태인지 확인합니다.
- 파일 형식이 JPG, PNG 또는 GIF인지 확인합니다.
- 파일 크기가 10MB 이하인지 확인합니다.
- 백엔드 로그를 확인합니다.

```powershell
docker compose logs --tail=100 backend-spring
```

### AI 분류 또는 RAG 질문이 실패하는 경우

- LM Studio API 서버와 `planner-model`, `answer-model`이 모두 실행 중인지 확인합니다.
- `rag-fastapi`와 `vector-db` 상태를 확인합니다.
- `.env`의 LM Studio 및 RAG 관련 주소를 확인합니다.

```powershell
docker compose ps
docker compose logs --tail=100 rag-fastapi
```

### RAG 답변 또는 학습 방향의 웹 자료가 나오지 않는 경우

- 일반 RAG와 학습 방향 모두 내부 자료가 연결되면 정책상 웹 검색을 실행하지 않는 것이 정상입니다.
- 일반 RAG는 요청의 `allow_web_search`가 `false`이면 내부 검색 실패 후에도 웹 검색을 실행하지 않습니다.
- 내부 자료도 없는데 일반 RAG가 근거 없음으로 끝나거나 학습 방향에 `추천 아이디어`만 표시되면 `web-search` health와 로그를 확인합니다.
- SearXNG는 API 키를 사용하지 않지만 외부 검색 엔진에 접근할 수 있는 인터넷 연결이 필요합니다.
- 웹 출처는 검색 결과 요약문 기반입니다. 중요한 답변은 출처 카드의 URL에서 원문을 확인합니다.

```powershell
docker compose ps web-search
docker compose logs --tail=100 web-search
```

ACL payload가 추가되기 전에 색인한 기존 Qdrant 청크는 검색에서 제외됩니다. 새 버전을 처음 실행한 뒤 다음 명령으로 전체 재색인을 수행하거나 관리자가 각 게시물의 `RAG 재색인`을 실행해야 합니다.

```powershell
docker compose exec rag-fastapi python scripts/reindex_all_posts.py
```

## 9. 개발용 프론트엔드만 실행

전체 Docker 서비스가 이미 실행 중이고 Next.js 화면만 개발 모드로 실행할 경우 다음 명령을 사용할 수 있습니다.

```powershell
cd C:\Users\user\Desktop\blogProject\frontend-nextjs
npm.cmd install
npm.cmd run dev
```

프론트엔드만 실행해도 게시글, 로그인, 이미지 및 RAG 기능을 사용하려면 Spring Boot 등의 백엔드 서비스가 별도로 실행 중이어야 합니다.

## 10. 종료 전 확인표

- `docker compose ps`로 실행 상태 확인
- 필요한 게시글과 이미지 백업 확인
- 일반 종료는 `docker compose stop` 또는 `docker compose down` 사용
- 데이터 보존이 필요하면 `-v` 옵션을 사용하지 않기
