# M07. Verification / Profiling / Benchmark

## 1. 책임

Patch가 실제로 안전하고 요구사항을 충족하는지 검증하고,
성능 변경은 실제 측정값으로 Before / After를 비교한다.

---

# 2. Verification Check Result

각 검증 항목:

```text
PASS
FAIL
INCONCLUSIVE
NOT_APPLICABLE
NOT_AVAILABLE
```

의미:

- PASS: 검증을 수행했고 요구 기준을 충족함
- FAIL: 검증을 수행했고 요구 기준을 충족하지 못함
- INCONCLUSIVE: 검증을 수행했거나 부분 수행했지만 변동성 / 재현성 / Evidence 불충분 등으로 PASS / FAIL을 확정할 수 없음
- NOT_APPLICABLE: 해당 프로젝트 / 변경에는 해당 검증이 의미상 적용되지 않음
- NOT_AVAILABLE: 적용 가능한 검증이나 환경/테스트 부족으로 실행 자체가 불가

`NOT_APPLICABLE`은 Verification 우회 수단으로 사용하지 않는다.

필수 원칙:

- required check를 `NOT_APPLICABLE`로 판정할 때는 명시적인 project metadata / test capability / deterministic rule / 승인된 policy에 근거해야 한다.
- Patch가 새로 추가·수정한 project metadata / test capability declaration만으로 required check를 스스로 `NOT_APPLICABLE`로 면제하지 않는다. Baseline inventory, trusted deterministic rule, independent capability evidence 또는 authorized policy decision으로 교차 확인한다.
- 단순히 테스트 파일을 찾지 못했다는 이유는 `NOT_APPLICABLE`이 아니라 원칙적으로 `NOT_AVAILABLE` 또는 추가 Evidence 필요로 처리한다.
- LLM은 `NOT_APPLICABLE` 후보와 rationale을 제안할 수 있지만 단독 authority로 required check를 N/A 확정하지 않는다.
- N/A 판정에는 `reason_code / rationale / evidence_reference / decision_authority` 또는 동등한 metadata를 남기고 M09 Audit에서 추적 가능해야 한다.

Patch 판정:

```text
any required FAIL
→ FAILED

no required FAIL
+ any required INCONCLUSIVE or NOT_AVAILABLE
→ INCONCLUSIVE

all required checks = PASS or NOT_APPLICABLE
→ VERIFIED 가능
```

---

# 3. Risk-based Verification Plan

Final Change Risk와 M03 acceptance criteria에 따라 최소 검증 범위를 생성한다.
Rule-based minimum required checks는 LLM / 사용자 편의 요청만으로 임의 제거하거나 낮은 수준으로 downgrade하지 않는다.
추가 check를 제안할 수는 있지만 required minimum을 제거하려면 명시적인 policy decision / rationale / Audit이 필요하다.

## LOW

```text
Canonical Change Set whitespace check (`git diff --check` + new/untracked change equivalent)
Static Check
Target Unit Test
```

## MEDIUM

```text
Canonical Change Set whitespace check (`git diff --check` + new/untracked change equivalent)
Static Check
Target Unit Test
Related Tests
Build Check
```

## HIGH

```text
Canonical Change Set whitespace check (`git diff --check` + new/untracked change equivalent)
Static Check
Target Unit Test
Related Unit Tests
Integration Tests
Build Check
필요 시 Regression Test
```

성능 변경은 Risk Level과 별개로 Before / After Benchmark를 추가한다.
MODIFY / OPTIMIZE의 behavior-changing 요청은 사용자 acceptance criteria / expected invariant가 최소 하나 이상의 Verification Check와 연결되어야 한다.
해당 behavior를 검증할 수 있는 executable / static Evidence가 존재하지 않으면 required intent check를 `NOT_AVAILABLE` 또는 `INCONCLUSIVE`로 처리하며 기존 regression check 통과만으로 요청 충족을 주장하지 않는다.
문서 / comment-only 등 behavior check가 의미상 적용되지 않는 변경은 M07의 엄격한 `NOT_APPLICABLE` 규칙을 따른다.

---

# 4. Verification Gate

Patch Verification 실행 전제:

```text
Worktree Apply = success
Canonical Actual Change Set = COMPLETE
Post-Apply Diff Guardrail = ALLOW
Final Change Risk / Verification Plan = available
```

위 선행조건을 충족하지 않으면 Verification을 시작하지 않는다.

```text
PATCH_APPLY_FAILED
→ verification 불가

VERIFYING
├─ VERIFIED
├─ FAILED
└─ INCONCLUSIVE
```

`VERIFIED`만 승인 대상으로 이동할 수 있다.

---

# 5. 자동 검증

Patch를 Temporary Worktree에 적용한 뒤 관련 테스트를 탐색한다.
Test / verification evidence에는 provenance를 구분한다. Provenance 분류는 LLM self-report가 아니라 trusted planner / test inventory / change-set evidence를 기준으로 결정한다.

```text
BASELINE_EXISTING_TEST
PATCH_MODIFIED_TEST
PATCH_ADDED_TEST
GENERATED_EPHEMERAL_CHECK
TRUSTED_EXTERNAL_HARNESS
```

Patch가 수정 / 추가한 테스트는 유용한 Evidence가 될 수 있지만 behavior-changing Patch의 유일한 성공 근거로 자동 승격하지 않는다.
가능한 경우 baseline에서 존재하던 target / related regression test와 trusted external / ephemeral acceptance check를 함께 사용한다.
Patch가 기존 required test를 삭제 / disable / skip하거나 test discovery / runner config를 변경해 검증 범위를 축소하면 Test Selection Integrity 위반으로 기록하고, 명시적 policy justification 없이는 `VERIFIED`로 통과시키지 않는다.
Patch가 required check를 실행하는 test runner / verification config / plugin / dependency / compiler / static toolchain 자체를 변경한 경우 그 Evidence provenance를 `PATCH_MODIFIED_VERIFICATION_TOOLCHAIN` 또는 동등하게 표시한다. 해당 변경된 toolchain만으로 Patch 성공을 증명하지 않고, 가능한 경우 baseline-pinned / trusted external harness 또는 독립된 secondary check로 교차 검증한다. 독립 검증이 required intent에 필요하지만 확보할 수 없으면 `INCONCLUSIVE`로 처리한다.
Verification은 `final_diff_hash`에 대응하는 exact source snapshot을 대상으로 수행해야 한다.
또한 Verification Result는 사용된 Final Risk threshold / Verification Plan / Guardrail / Command Policy / Sandbox profile의 policy bundle을 식별하는 `verification_basis_id` 또는 동등한 basis hash에 연결한다.
`verification_basis_id`에는 최소한 risk rule version + risk threshold version, required-check plan/version, `request_intent_id` 또는 protected request reference/hash + acceptance-criteria mapping hash/version, Guardrail / Command / Sandbox policy version, Verification에 사용된 security exception decision reference, required `NOT_APPLICABLE` decision reference를 포함하거나 무결성 연결해야 한다.
최종 CheckResult 집합과 required `NOT_APPLICABLE` / security exception / toolchain provenance decision이 확정된 뒤 Verification Result와 finalized `verification_basis_id`를 M09에 crash-consistent하게 연결하여 저장한다. 이 durable linkage가 실패하면 해당 결과를 Approval authority로 사용하지 않는다.

대상:

- Unit Test
- Integration Test
- Static Check
- Build Check
- Canonical Change Set whitespace check (`git diff --check` + new/untracked change equivalent)

실행하지 않은 검증을 실행했다고 주장하지 않는다.
Verification Plan은 baseline test inventory / post-patch test inventory 또는 동등한 Evidence를 비교해 required test가 예상 밖으로 사라지거나 skip되지 않았는지 확인할 수 있어야 한다.

Verification Environment Integrity 원칙:

- Verification 시작 전 source snapshot / `final_diff_hash` 기준점을 기록한다.
- Test / Build / Profiler / Static 실행 후 Canonical Actual Change Set의 모든 source entry와 relevant source snapshot이 변경되지 않았는지 확인한다. tracked file뿐 아니라 Patch-created untracked / ignored source도 포함한다.
- 검증 도구가 tracked source 또는 Patch-created untracked / ignored source를 변경하거나 예상 밖 source entry를 생성하면 해당 실행의 결과를 Patch 검증 Evidence로 확정하지 않고 `INCONCLUSIVE` 또는 execution-invalid로 기록한다.
- exact Patch snapshot을 복원한 뒤 해당 required check를 재실행할 수 있어야 한다.
- 반복 실행에서도 source mutation을 제거할 수 없으면 Patch 전체를 `INCONCLUSIVE`로 판정한다.

---

# 6. CPU / Runtime Profiling

1차 구현: Python

분석:

- CPU usage
- function execution time
- call count
- memory usage
- allocation
- peak memory

후보 도구:

```text
기본: cProfile
기본: tracemalloc
선택: py-spy
별도: process CPU time / CPU utilization collector
```

`cProfile`과 `tracemalloc`만으로 process-level CPU utilization을 직접 대체하지 않는다.
CPU usage가 Verification / Benchmark의 요구 지표인 경우 process CPU time 또는 CPU utilization을 수집할 별도 측정기를 사용한다.
구체 측정 도구와 sampling 방식은 Architecture / Detailed Design에서 확정한다.

`py-spy`는 다른 프로세스 추적에 추가 capability가 필요할 수 있으므로 1차 구현의 기본 Verification Sandbox 권한으로 강제하지 않는다.
필요 시 전용 Profiling Sandbox에서 최소 권한(`SYS_PTRACE` 등)만 별도로 허용하고, 일반 Test / Verification Sandbox와 권한 경계를 분리한다.

---

# 7. Memory / Allocation

Python 1차 구현은 Java식 Heap Dump보다 다음을 우선한다.

- tracemalloc snapshot
- allocation hotspot
- 객체 증가
- peak memory
- cache growth
- resource release 후보
- GC 부담 후보

---

# 8. Evidence-based Optimization

```text
Source
+
Potpie
+
Static Analysis
+
Profiler
+
Test
→ Qwen Recommendation
```

Profiler / Test / Static 결과 수집이 Qwen 최적화 판단보다 먼저다.

---

# 9. Before / After Benchmark

비교 항목:

- execution time
- average latency
- P95
- CPU
- peak memory
- allocation
- call count

원칙적으로 동일 조건을 사용한다.
Patch 자체가 dependency / runtime / compiler configuration 변경을 포함하는 경우 그 차이는 의도된 treatment로 명시적으로 기록하고, 그 외의 비의도적 환경 차이는 허용하지 않는다.
Before / After의 environment fingerprint가 비의도적으로 달라 비교 가능성을 확보할 수 없으면 required Benchmark를 `INCONCLUSIVE`로 판정한다.

Benchmark harness / dataset / measurement code가 Patch에 의해 변경되는 경우 그 provenance를 기록하고, 성능 개선을 증명하는 primary benchmark는 가능한 경우 Patch와 독립된 immutable / trusted harness를 사용한다.
Patch가 benchmark harness 자체를 바꾼 결과만으로 성능 향상을 확정하지 않는다.

Benchmark 결과는 단일 실행값만으로 성능 개선 여부를 확정하지 않는다.
동일 조건의 반복 측정을 기반으로 비교한다.

Benchmark가 해당 `OPTIMIZE` / 성능 변경의 Verification Plan에서 required check인 경우,
측정 변동성 또는 재현성 제한 때문에 개선 여부를 확정할 수 없으면 해당 Benchmark `CheckResult`를 `INCONCLUSIVE`로 기록하고 Patch 전체 Verification Result도 `INCONCLUSIVE`로 판정한다.
required benchmark의 판단 불가를 단순 reproducibility limitation만 표시한 채 `VERIFIED`로 통과시키지 않는다.

Benchmark가 required check가 아닌 보조 Evidence인 경우에는 결과와 reproducibility limitation을 함께 기록할 수 있다.

---

# 10. Benchmark Reproducibility

기록:

```text
dataset hash
runs
warmup
Python version
dependency version / lockfile hash / resolved artifact digest-or-origin reference
OS
CPU / GPU
memory
relevant environment
benchmark / environment fingerprint
dependency / runtime change as intended treatment 여부
base commit
patch / changed commit
```

조건이 동일하지 않으면 재현성 제한을 표시한다.

---

# 11. Patch Revision / Verification Basis 연계

Patch hash / final diff hash가 변경되면 이전 Verification Result를 재사용하지 않는다.
Approval / Apply 시점에 current risk threshold / guardrail / verification policy basis가 저장된 `verification_basis_id`와 달라지고 명시적 backward compatibility가 확인되지 않으면 기존 Verification Result를 재사용하지 않는다.
Policy backward-compatibility는 LLM 단독 판단이 아니라 versioned trusted policy / deterministic compatibility rule 또는 authorized administrative decision으로 판정하고 decision reference를 Verification Basis / Audit에 연결한다.

동일 Patch에서 부족한 검증만 추가하는 경우에만 기존 revision을 유지할 수 있다.

---

# 12. 출력

```text
VerificationPlan
AcceptanceCriteriaMapping[]
TestEvidenceProvenance[]
CheckResult[]
VerificationResult
ProfilerResult
BenchmarkResult
ReproducibilityMetadata
VerificationBasisReference
VerificationEnvironmentFingerprint
```

---

# 13. 성공 기준

- Risk와 acceptance criteria에 따른 최소 검증 계획을 만든다.
- behavior-changing Patch는 원 사용자 요청의 `request_intent_id` / protected request reference에서 유도된 acceptance criteria를 Verification Evidence와 연결하며, 검증 불가한 intent를 regression PASS만으로 충족했다고 주장하지 않는다.
- LLM / 사용자 요청만으로 deterministic required minimum check를 임의 downgrade하지 않는다.
- baseline existing test와 patch-modified / added / generated test provenance를 구분하고, Patch가 검증 범위를 자체적으로 축소 / 우회한 결과를 정상 PASS로 취급하지 않는다.
- primary performance claim은 가능한 경우 Patch와 독립된 benchmark harness로 검증한다.
- Worktree / Post-Apply Guardrail / Final Risk 선행조건을 우회한 Patch Verification을 허용하지 않는다.
- Verification 전후 Canonical Actual Change Set 전체 / source snapshot / final diff integrity를 확인하고, 검증 도구에 의한 tracked / Patch-created untracked source mutation이 있는 Evidence를 그대로 `PASS`로 사용하지 않는다.
- FAIL / INCONCLUSIVE / NOT_AVAILABLE을 올바른 Patch 상태로 반영한다.
- required check의 `NOT_APPLICABLE` 판정은 근거 / authority를 기록하며 LLM 단독 판단으로 Verification을 우회하지 않는다.
- whitespace / static validation은 Canonical Actual Change Set의 new/untracked Patch-created file까지 필요한 범위에서 포함한다.
- 성능 개선 여부를 단일 실행이 아닌 반복된 실제 측정값으로 판단한다.
- CPU usage가 요구 지표인 경우 별도 process-level CPU 측정기를 사용할 수 있다.
- 동일 조건 Before / After를 비교하며, 의도된 dependency / runtime 변경은 treatment로 명시적으로 기록한다.
- 비의도적 environment fingerprint 차이로 비교 가능성이 깨지면 required Benchmark를 `INCONCLUSIVE`로 처리한다.
- Benchmark reproducibility metadata를 저장한다.
- required Benchmark에서 개선 여부를 확정할 수 없으면 Verification Result를 `INCONCLUSIVE`로 판정한다.
- 보조 Benchmark의 재현성 제한은 결과와 함께 명시적으로 기록한다.
- patch hash / final diff hash 변경 시 이전 Verification Result를 재사용하지 않는다.
- Verification Result가 어떤 risk rule / threshold / acceptance-criteria mapping / verification / guardrail / command / sandbox policy basis에서 생성되었는지 식별할 수 있다.
- Verification에 사용된 주요 runtime / toolchain / dependency / command-template version을 environment fingerprint 또는 동등한 provenance로 기록할 수 있다.
