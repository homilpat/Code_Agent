# M08. Local-Only Security

## 1. 책임

사내 비밀 코드와 분석 데이터가 외부 서비스로 유출되지 않도록
Local-Only 실행 경계를 강제하고 검증한다.

---

# 2. 외부 서비스 금지

```text
OpenAI API       금지
Anthropic API    금지
Gemini API       금지
External Embedding 금지
External Web Search 금지
```

사용 대상:

```text
Local Repository
Local LLM
Local Embedding
Local Database
Local Vector DB
Local Code Graph
Local Profiler
Local Test Runner
```

---

# 3. Network Policy

```text
Internet Egress
DEFAULT = BLOCK

Internal Network
DEFAULT = DENY

Allow
= Explicit Allowlist Only
```

Git partial-clone / promisor / LFS / submodule / object-store 기능도 암묵적 예외가 아니며, local analysis / Safe Git introspection 중 자동 network fetch를 수행하지 않는다. 필요한 internal fetch는 명시적 allowlist / trusted control-plane 경로와 Audit을 요구한다.

Docker internal network / host firewall 등으로 강제한다.

---

# 4. Runtime Verification

다음 상태를 실행 시 확인한다.

```text
LLM Provider      LOCAL
Embedding         LOCAL
Repository        LOCAL
Code Graph        LOCAL
Telemetry         DISABLED
External API      DISABLED
Internet Egress   BLOCKED
Potpie Runtime    LOCAL
Potpie Provider   LOCAL ONLY
```

외부 LLM / embedding / provider 설정을 탐지하면 Code Intelligence 실행을 차단한다.
상태 조회 화면이나 CLI에서는 차단 원인을 경고로 표시할 수 있지만, Local-Only 필수 조건을 위반한 상태에서 분석 / Retrieval / LLM 실행을 계속하지 않는다.

---

# 5. Sensitive File Policy

Sensitive File은 기본적으로 ingestion / Retrieval / LLM context 및 untrusted Sandbox runtime source view에서 제외한다.
Repository 내부 symlink / junction을 통해 Sensitive File 또는 canonical Repository root 밖의 파일을 우회적으로 읽는 것도 동일하게 차단한다.
Sensitive classification은 path pattern만으로 한정하지 않고, high-confidence credential / private-key / token pattern 또는 trusted secret scanner가 탐지한 content도 policy input으로 사용할 수 있어야 한다. 탐지된 content를 LLM에 먼저 넣은 뒤 마스킹하는 방식으로 대체하지 않는다.
Git history / blame / historical diff를 Evidence로 사용할 때도 동일한 ACL / Sensitive Policy를 적용한다. 최근 변경 빈도처럼 metadata만 필요한 Risk factor는 raw historical source content를 LLM context에 넣지 않고 metadata Evidence를 우선한다.

Sensitive File modification은 기본 차단한다.

예외가 필요한 경우 명시적인 local policy allowlist와 권한 확인을 요구하며, 예외는 사용 시점마다 scope / expiry / current authorization을 재확인하고 사용 사실을 M09 Audit에 기록해야 한다.

Sensitive File 예외는 최소 다음 범위로 제한할 수 있어야 한다.

```text
user / role
repository
path / path pattern
operation (read-context / runtime-read / modify / declassify / remote-publish 등)
policy version
필요 시 expiry / one-shot scope
```

`read-context`, `runtime-read`, `modify`, `declassify`, `remote-publish` 예외는 서로 독립적으로 승인한다.
민감 파일 수정 예외가 존재한다는 이유만으로 raw file content를 Retrieval / LLM context 또는 Sandbox runtime에 포함하지 않는다.
`read-context` exception을 통해 Sensitive File content가 LLM context에 포함된 경우 그 content를 포함하거나 재구성할 수 있는 answer / analysis result는 sensitive context-derived result로 분류하고 일반 Audit / Web payload에 raw content를 자동 저장하지 않는다. 필요 시 protected Local Store / current ACL을 적용한다.
Sensitive `read-context` 또는 protected `runtime-read` 결과가 LLM / Planner / Patch Generator의 Evidence로 사용된 경우, 해당 downstream answer / plan / patch / derived artifact에는 `sensitive_provenance` 또는 동등한 보수적 label을 전파한다. 실제 secret 문자열의 완전한 정보흐름 추적을 전제로 하지 않으며, 명시적 declassification policy가 없는 한 해당 label을 자동 제거하지 않는다.
`sensitive_provenance`의 생성 / 전파 / 제거 결정은 LLM output의 self-report를 신뢰하지 않고 trusted orchestrator / policy layer가 Evidence lineage와 policy decision을 기준으로 관리한다. Model이 label 제거를 요청하거나 출력에서 생략해도 trusted metadata를 자동 해제하지 않는다.
Sensitive content에 대한 `read-context` 또는 `modify` 권한은 해당 값을 non-sensitive file / 일반 output / Remote Provider로 복사·공개하는 declassification 권한을 자동으로 부여하지 않는다.
`sensitive_provenance`가 붙은 derived content를 더 낮은 보호 등급의 local source / output으로 materialize하려면 destination classification을 유지하거나 별도의 scoped `declassify` decision을 요구한다. Provenance label 자체는 secret disclosure의 확정 증거가 아니라 보수적인 보호 신호이며, 명시적 declassification 없이 자동 downgrade하지 않는다.
Sandbox runtime에서 Sensitive File을 읽어야 하는 경우 별도의 scoped `runtime-read` exception과 권한 확인을 요구한다.
`runtime-read` exception을 사용한 실행 결과는 sensitive execution result로 분류하며, 단순 문자열 masking만으로 일반 결과와 동일한 공개 범위를 부여하지 않는다. Raw result가 보존되는 경우 일반 Audit payload와 분리된 보호 저장소 / ACL을 사용하고, 필요성이 없으면 폐기한다.
Sensitive runtime-read와 network allowlist를 동시에 요구하는 경우 별도의 combined policy decision / 최소 scope / Audit 없이는 허용하지 않는다.
Sensitive File 또는 `sensitive_provenance`가 연결된 derived content를 allowlisted internal Git Provider로 전송하는 Remote operation에는 scoped `remote-publish` authorization이 필요하다. Non-sensitive Remote operation도 Local Apply 승인에서 자동 파생되지 않으며 별도의 explicit remote intent / current Remote permission을 요구한다. Remote destination이 현재 보호 범위보다 낮거나 provenance downgrade가 발생하면 `remote-publish`와 별도로 scoped `declassify` decision도 요구한다. 두 권한은 서로 대체하지 않으며 사용 사실을 Audit에 기록한다.
M06 Guardrail / Sandbox는 이 정책 결정을 소비하며, 범위를 벗어난 context 제공 / runtime read / modification을 기본 차단한다.

예:

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

# 6. Logging Security

금지:

- API key 원문 저장
- token 원문 저장
- password
- private key
- 전체 source code를 Audit payload로 저장
- 민감 환경변수
- CLI / Web authentication credential, Remote Git provider credential 또는 Host agent socket을 LLM context / untrusted Sandbox runtime에 상속
- credential 가능성이 있는 raw profiler output
- secret redaction 전의 raw sandbox stdout / stderr / test artifact를 일반 Audit / Web payload로 저장

---

# 7. Potpie Security

Potpie는 Self-hosted only.

외부 cloud / provider / telemetry를 허용하지 않는다.

---

# 8. Sandbox Security

- Host 직접 실행 기본 금지
- Host / CLI / Remote Git provider credential / auth-agent socket runtime 상속 금지
- egress block
- allowlisted internal dependency source만 사용
- docker socket 직접 접근 금지
- destructive command 차단

---

# 9. 의존 모듈

- 전 모듈 공통
- 특히 M01 / M02 / M06 / M09

---

# 10. 성공 기준

- 외부 API 없이 핵심 기능이 동작한다.
- 외부 LLM / embedding / provider 설정이 탐지되면 Code Intelligence 실행을 차단한다.
- egress 차단 상태를 검증할 수 있다.
- untrusted Sandbox runtime이 Host / CLI credential / agent socket을 기본적으로 상속하지 않는다.
- 민감 파일 및 high-confidence secret content가 기본적으로 ingestion / Retrieval / LLM context에 유입되지 않도록 path + content classification을 적용할 수 있다.
- Git history / historical diff Evidence도 current ACL / Sensitive Policy를 우회하지 않는다.
- 민감 파일 modification은 기본 차단되며, 예외는 명시적 scoped allowlist + 권한 확인 + Audit 없이 허용되지 않는다.
- Sensitive File의 Retrieval / LLM context, Sandbox `runtime-read`, modification, `declassify`, `remote-publish` 예외를 서로 독립적으로 강제할 수 있다.
- scoped runtime-read exception이 없는 Sensitive File은 untrusted Sandbox runtime에서 기본 비가시화한다.
- Sandbox output의 secret이 일반 Audit / Web payload로 원문 노출되지 않도록 redaction / sensitive-result isolation을 적용할 수 있다.
- Sensitive runtime-read 또는 read-context를 사용한 downstream artifact에 보수적인 `sensitive_provenance`를 전파하고 ACL / Web / Remote 노출 범위를 제한할 수 있다.
- Sensitive runtime-read와 network allowlist의 고위험 조합은 명시적인 combined exception 없이 허용되지 않는다.
- symlink / junction을 통한 Sensitive File / Repository root 밖 source ingestion 우회를 차단한다.
- Potpie도 Local-Only로 검증된다.
