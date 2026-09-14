# M03. Query Planner / Code Understanding

## 1. 책임

사용자 자연어 질의를 구조화하고,
코드 설명 / 영향 분석 / 수정 / 성능 분석 등 적절한 실행 경로로 라우팅한다.

---

# 2. Planner 모델

## M03-FR-01. Domain

```text
KNOWLEDGE
CODE
```

---

## M03-FR-02. Task

```text
EXPLAIN
IMPACT
MODIFY
PERFORMANCE
OPTIMIZE
VALIDATE
```

---

## M03-FR-03. Reasoning Intent

```text
FACT_LOOKUP
COMPARISON
CAUSE_ANALYSIS
TROUBLESHOOTING
DESIGN_PROPOSAL
NOVELTY_ASSESSMENT
VALIDATION_PLAN
```

한 질문이 Task와 Reasoning Intent를 동시에 갖는다.

예:

```text
"왜 이 함수가 느려?"

domain = CODE
task = PERFORMANCE
reasoning_intent = CAUSE_ANALYSIS
```

---

# 3. Planner 출력

최소 다음 정보를 표현할 수 있어야 한다.

```json
{
  "domain": "CODE",
  "task": "OPTIMIZE",
  "reasoning_intent": "CAUSE_ANALYSIS",
  "resolved_query": "...",
  "target_entities": ["build_candidates"],
  "needs_retrieval": true,
  "needs_runtime_evidence": true,
  "needs_impact_analysis": true,
  "needs_clarification": false,
  "acceptance_criteria": ["...expected behavior / invariant..."]
}
```

구체 schema는 상세설계에서 확정한다.

Planner는 MODIFY / OPTIMIZE / VALIDATE에서 사용자 요청으로부터 검증 가능한 acceptance criteria / expected invariant를 가능한 범위에서 구조화한다.
모델 변환 이전에 trusted orchestrator가 원 사용자 command / request를 immutable request envelope로 캡처하고 `request_intent_id` 또는 동등한 stable reference를 부여한다. LLM / Repository Evidence는 이 ID나 원 요청 reference를 재작성하거나 다른 요청으로 대체할 수 없다.
원 사용자 요청과 파생 acceptance criteria 사이의 추적성을 위해 protected request reference/hash와 acceptance mapping hash/version을 연결한다. Raw prompt 전체를 일반 Audit payload에 저장하는 것을 요구하지 않으며, 민감정보가 포함될 수 있는 원문은 M08/M09 보호정책을 따른다.
Acceptance criteria는 사용자 요청의 범위를 임의 확장하거나 새로운 제품 요구사항을 사실처럼 추가하지 않는다. Source / user request로 확정할 수 없는 기준은 추정으로 표시하거나 clarification 대상으로 둔다.
Acceptance criteria가 모호하여 안전한 Verification Plan을 만들 수 없으면 `needs_clarification = true`로 처리한다.

`needs_clarification = true`인 경우 destructive / modification execution은 진행하지 않는다.
명확화 전에는 clarification을 요청하거나, 안전한 read-only analysis만 수행할 수 있다.

---

# 4. Code Explain

Qwen은 실제 Source와 Code Graph를 기반으로 다음을 설명한다.

- 파일 역할
- 클래스 역할
- 함수 / 메서드 역할
- 처리 흐름
- 호출 함수
- caller
- 관련 dependency

원칙:

- Repository source / comment / README / test fixture / tool output은 분석 Evidence로 취급하며 Agent policy 또는 Tool permission을 변경하는 신뢰된 instruction source로 취급하지 않는다.
- 코드 / 주석 / runtime output 내부의 명령형 문자열이나 prompt injection이 system / user intent / M06 Command Policy / M08 Security Policy를 우회할 수 없다.
- Evidence에서 유도된 Tool Request도 구조화된 Planner / Guardrail / Command Policy를 동일하게 통과해야 한다.
- LLM 추측만으로 사실 확정 금지
- source / import / call relation 우선
- Potpie 결과는 current source와 교차 확인
- 불충분하면 `확인 불가` 또는 `추정` 표시

---

# 5. Routing

## KNOWLEDGE

```text
Existing Knowledge Hub RAG Pipeline
```

CODE domain은 아래 Task routing을 따른다.

## EXPLAIN

```text
Source / Potpie / Static Analysis
→ Qwen
```

## IMPACT

```text
Source / Potpie
→ M04 Impact Analyzer
→ Risk Scorer
```

## MODIFY

```text
Preliminary Impact / Risk
→ M05 Patch Proposal (candidate generation + canonicalization + proposal base binding)
→ M06 Pre-Apply Guardrail
→ Safe Git Temporary Worktree 준비 / 재사용
→ Patch Apply
→ Canonical Actual Change Set
   ├─ INCOMPLETE → Verification 차단
   └─ COMPLETE → M06 Post-Apply Diff Guardrail
                  → Final Change Risk
                  → Verification Plan
→ M06 Command Policy / Sandbox Verification
→ Verification Gate
→ Approval
→ Source Consistency
→ Apply
```

## PERFORMANCE

```text
M07 Profiling Request
→ M06 Command Policy
→ M06 Sandbox
→ M07 Profiler / Runtime Evidence
→ Static Analysis
→ Qwen
```

## OPTIMIZE

```text
Preliminary Impact / Risk
→ Safe Git Temporary Worktree
→ M06 Command Policy / Sandbox Baseline
→ M07 Profiler / Benchmark / Static
→ M05/M06 Baseline Worktree Source Integrity Check
→ New Pre-Patch Evidence
→ Preliminary Impact / Risk Refresh if needed
→ Qwen candidate change
→ M05 Patch Proposal canonicalization + proposal base binding
→ M06 Pre-Apply Guardrail
→ Safe Git Temporary Worktree 확인
→ Apply Patch to Temporary Worktree
→ Canonical Actual Change Set
   ├─ INCOMPLETE → Verification 차단
   └─ COMPLETE → M06 Post-Apply Diff Guardrail
                  → Final Risk
                  → Verification Plan
→ M06 Command Policy / Sandbox Test / Benchmark
→ Verification Gate
→ Approval
→ Source Consistency
→ Apply
```

## VALIDATE

```text
Current Patch / Target
→ Verification Requirement Resolve
→ M07 Verification Plan
→ M06 Command Policy / Sandbox
→ M07 Verification Gate
```

---

# 6. 의존 모듈

- M02 Source / Graph
- M04 Impact / Risk
- M05 Patch Lifecycle
- M06 Command Policy / Sandbox
- M07 Verification / Profiling

---

# 7. 성공 기준

- 코드 질의와 기존 Knowledge 질의를 분리할 수 있다.
- KNOWLEDGE 질의는 기존 Knowledge Hub RAG 경로로 전달할 수 있다.
- Task와 Reasoning Intent를 독립적으로 표현한다.
- MODIFY / OPTIMIZE / VALIDATE 요청의 acceptance criteria / expected invariant를 Verification Plan으로 전달할 수 있다.
- 원 사용자 요청의 `request_intent_id` / protected request reference와 acceptance mapping을 Verification Basis까지 추적 가능하게 연결할 수 있다.
- Explain 결과가 Source Evidence에 근거한다.
- VALIDATE가 M06 / M07 검증 경로로 연결된다.
- `needs_clarification = true`인 상태에서 destructive / modification execution을 진행하지 않는다.
- PERFORMANCE / OPTIMIZE의 runtime 실행은 M06 Command Policy / Sandbox 경로를 우회하지 않는다.
- OPTIMIZE baseline 실행 부산물이 Worktree source 또는 이후 Canonical Actual Change Set를 오염시키지 않았는지 확인한 뒤 Patch 생성 / 적용 단계로 진행한다.
- 새로운 pre-patch runtime/static evidence가 확보되면 Preliminary Risk를 최신 Evidence 기준으로 갱신할 수 있다.
- MODIFY / OPTIMIZE의 Patch는 Worktree 적용 전에 M06 Pre-Apply Guardrail을 통과한다.
- MODIFY / OPTIMIZE가 검증 파이프라인을 우회하지 않는다.
