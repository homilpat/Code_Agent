# Evals: 로컬 모델 코드 수정 go/no-go 평가

로컬 모델이 최소한의 수정 루프로 실제 버그를 고칠 수 있는지 측정합니다. 제품(code-agent)의 샌드박스·권한·감사 경계와는 무관한 **평가용 러너**입니다. 표준 라이브러리만 사용합니다.

## 흐름

1. 과제의 고정 기준 커밋에서 `git archive`로 임시 작업 폴더를 만듭니다.
2. 문제 설명과 문맥 파일을 모델에 전달합니다.
3. 모델은 SEARCH/REPLACE 블록으로만 답합니다. 러너가 적용하며, 블록은 파일에서 정확히 한 번만 일치해야 하고 답변 단위로 전부 적용되거나 전부 거부됩니다.
4. 숨김 테스트를 넣고 전체 테스트를 실행합니다. 실패하면 테스트 출력과 현재 파일 내용을 돌려주고 최대 N회 반복합니다.
5. 결과를 `evals/results/<시각>_<모델>.jsonl`에 기록합니다(git 제외).

## 실행

저장소 루트에서, 대상 프로젝트(code-agent)의 테스트 의존성이 설치된 Python으로 실행합니다. 작업 폴더의 `src`가 editable install보다 먼저 import되는지 매 과제마다 확인합니다.

```powershell
# 과제 검증: 기준 커밋에서 숨김 테스트가 실패하고, 정답 패치로 전체 통과해야 VALID
python -m evals.runner validate

# LM Studio 서버(기본 http://localhost:1234/v1)에 모델을 올린 뒤 평가
python -m evals.runner run --model qwen/qwen3.6-35b-a3b --attempts 3

# 러너 단위 테스트
python -m pytest evals/tests -p no:cacheprovider
```

## 과제 형식 (`evals/tasks/<id>/`)

| 파일 | 내용 |
|---|---|
| `task.json` | `base_commit`, `repo_subdir`, `context_files`, `hidden_tests`, `fail_to_pass`, 출처 |
| `issue.md` | 모델에게 주는 문제 설명 |
| `hidden/` | 테스트 실행 직전에 복사되는 숨김 테스트. 모델 수정으로 덮어쓸 수 없음 |
| `solution.edits` | 정답 패치(SEARCH/REPLACE). 과제가 풀 수 있는지 `validate`에서 확인 |

## 판정

| 판정 | 의미 |
|---|---|
| `PASS` | `fail_to_pass` 테스트가 모두 통과하고 다른 실패가 없음 |
| `TEST_FAIL` | 필요한 테스트가 아직 실패 |
| `REGRESSION` | 필요한 테스트는 통과했지만 다른 테스트가 실패 |
| `FORMAT_ERROR` / `APPLY_ERROR` | 블록 형식 오류 / 파일·일치 문제로 적용 실패 |
| `TRUNCATED` | `max_tokens`에서 잘려 블록이 없음 |
| `TIMEOUT`, `LLM_ERROR`, `HARNESS_ERROR` | 테스트 시간 초과, 모델 호출 실패, 러너 환경 문제 |

실패한 테스트는 최대 2회 다시 실행하며, 재실행에서 통과한 테스트는 숨기지 않고 `flaky`로 기록합니다.

## 현재 한계

- 문맥 파일을 과제가 직접 지정합니다(파일 탐색 능력은 측정하지 않음).
- 과제 2개, 모두 한 파일 몇 줄 수정입니다. go/no-go 판단에는 20~30개가 필요합니다.
- 테스트는 호스트에서 격리 없이 실행합니다. 신뢰할 수 있는 과제에만 사용합니다.

## 기록

| 날짜 | 모델 | 기준 커밋 | 결과 | 비고 |
|---|---|---|---|---|
| 2026-09-14 | qwen/qwen3.6-35b-a3b (Q4_K_M, 32K, LM Studio, A4000) | `b8060c7` | 2/2 PASS | ca-001 1회, ca-002 2회(첫 답이 프롬프트 예시의 `path/` 접두어를 따라 써 APPLY_ERROR). 과제당 약 4분, 대부분 모델 응답 시간(약 8 tok/s) |
