# M04. Change Impact / Risk Analysis

## 1. 책임

변경 전 예상 영향범위와 실제 Patch 적용 후 영향범위를 분석하고,
Rule-based Risk Score를 산출한다.

LLM은 Risk Score 숫자를 직접 결정하지 않는다.

---

# 2. Change Impact / Blast Radius

분석 대상:

- direct caller
- indirect caller
- related tests
- test / benchmark harness 및 verification config
- config
- persistence
- external dependency
- API contract
- shared symbol
- runtime boundary

---

# 3. Preliminary Risk

Patch 생성 전에 계산한다.

근거:

```text
User Request
+
Target Symbol
+
Current Call Graph
+
External Boundary
+
Current Test Coverage
```

용도:

- 변경 계획
- Patch 생성 전략
- 예상 검증 범위

Preliminary Risk는 Verification Authority가 아니다.

Patch 생성 전 Profiler / Static Analysis 등 새로운 Evidence가 추가되면 Preliminary Risk를 최신 Evidence 기준으로 재계산할 수 있다.
재계산된 최신 Preliminary Risk는 이후 변경 계획과 Patch 생성 전략에 사용하되, 이전 계산 이력은 Audit에서 추적 가능해야 한다.
Preliminary Risk의 재계산은 Canonical Actual Change Set 기반 Final Change Risk를 대체하지 않는다.

---

# 4. Final Change Risk

Patch를 Temporary Worktree에 적용한 뒤
M05가 생성한 `Canonical Actual Change Set`을 기준으로 다시 계산한다.
단순 `git diff` 출력만을 전체 변경의 authority로 사용하지 않는다.

근거:

```text
Canonical Actual Change Set
+
Changed Files
+
Changed Symbols
+
Updated Blast Radius
+
Config / API / Persistence Change
+
Security Impact
+
File type / mode / symlink / submodule change
```

Final Change Risk가 최종 Verification Plan을 결정한다.
M06 / M08에서 허용된 sensitive-file / security policy exception도 `Security Impact` Evidence로 유지하며, Guardrail에서 허용되었다는 이유만으로 Risk factor에서 제거하지 않는다.

---

# 5. Risk Score

후보 요소:

- caller 수
- dependency 수
- cyclomatic complexity
- test coverage
- test deletion / modification / skip-config 영향
- 최근 변경 빈도
- runtime hotspot
- external boundary
- shared symbol
- persistence 영향
- security 영향
- symlink / executable mode / gitlink / special file type 영향

기본 threshold:

```text
0  - 39   LOW
40 - 69   MEDIUM
70 - 100  HIGH
```

Threshold는 설정 가능해야 하고,
결과에 사용한 threshold version과 Risk rule / scoring algorithm version을 기록한다.
가중치 / factor normalization / missing-evidence 처리 규칙 등 Risk 계산 semantics가 바뀌면 `risk_rule_version` 또는 동등한 버전을 변경해야 하며, threshold가 동일하다는 이유만으로 이전 Risk semantics와 동일하다고 간주하지 않는다.

Risk factor evidence가 `unavailable`인 경우 해당 요소를 임의로 0점 처리하지 않는다.
Missing evidence는 `RiskFactors`에 명시적으로 기록하고,
필요한 Evidence가 부족하면 Verification Plan을 보수적으로 확대할 수 있어야 한다.

---

# 6. Rule-based Score → LLM Explanation

```text
Rule-based Score
→ Risk Level
→ Qwen Explanation
```

Qwen은 Risk 원인을 설명할 수 있지만 점수를 임의 생성하지 않는다.

---

# 7. Patch revision과 Risk

Patch 내용이 변경되면:

```text
old final risk → invalid
new Canonical Actual Change Set → recompute final risk
new verification plan
```

기존 Final Risk를 새 revision에 재사용하지 않는다.

---

# 8. 출력

```text
ImpactResult
PreliminaryRisk
FinalChangeRisk
RiskLevel
RiskFactors
MissingRiskEvidence
ThresholdVersion
RiskRuleVersion
ChangedSymbols
AffectedTests
```

---

# 9. 의존 모듈

- M02 Repository / Graph
- M05 Canonical Actual Change Set
- M07 Verification Planner

---

# 10. 성공 기준

- 변경 영향 범위를 식별한다.
- Preliminary Risk와 Final Risk를 구분한다.
- Canonical Actual Change Set / `final_diff_hash`가 바뀌면 Final Risk를 다시 계산한다.
- Risk evidence가 부족한 요소를 임의의 안전한 값으로 축소하지 않는다.
- Missing Risk Evidence를 결과에 기록할 수 있다.
- Patch 생성 전 새로운 Evidence가 확보되면 Preliminary Risk를 재계산할 수 있다.
- 허용된 security policy exception도 Final Risk Evidence로 반영할 수 있다.
- Risk Level이 Verification Plan과 연결된다.
- Risk 계산 semantics / threshold가 어떤 version에서 산출되었는지 식별할 수 있다.
