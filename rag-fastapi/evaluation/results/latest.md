# Knowledge Hub RAG Evaluation

- 실행 시각: 2026-09-04T02:16:15+00:00
- Golden set: 50문항

## Retrieval

| 전략 | 문항 | Hit@K | Recall@K | MRR | 평균 지연(ms) |
|---|---:|---:|---:|---:|---:|
| dense | 50 | 0.900 | 0.900 | 0.890 | 31.6 |
| hybrid | 50 | 0.860 | 0.860 | 0.850 | 25.5 |
| hybrid_rerank | 50 | 0.860 | 0.860 | 0.840 | 5335.2 |

## Generation

| 프로필 | 문항 | 통과율 | 정확성 | 근거 블록 | 인용 유효성 | 평균 지연(ms) |
|---|---:|---:|---:|---:|---:|---:|
| qwen_direct:dense | 50 | 0.820 | 0.870 | 0.893 | 1.000 | 21270.6 |
| hierarchical:dense | 50 | 0.940 | 0.938 | 0.810 | 1.000 | 33438.5 |
| auto:dense | 50 | 0.880 | 0.896 | 0.840 | 1.000 | 25769.5 |

## Auto routing

| 문항 | 경로 정확도 | Intent 정확도 | 구조 정확도 | 잘못된 직접 | 불필요한 계층형 | 우회 실패 |
|---:|---:|---:|---:|---:|---:|---:|
| 50 | 0.740 | 0.700 | 0.700 | 11 | 1 | 1 |

## Quality by expected question structure

| 프로필 | 구조 | 문항 | 통과율 | 정확성 | 근거 블록 | 인용 유효성 | 평균 지연(ms) | 경로 분포 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| qwen_direct:dense | DIRECT_LOOKUP | 21 | 0.762 | 0.852 | 0.921 | 1.000 | 20686.2 | qwen_direct:21 |
| qwen_direct:dense | COMPARATIVE | 7 | 1.000 | 0.989 | 1.000 | 1.000 | 21601.4 | qwen_direct:7 |
| qwen_direct:dense | CAUSAL | 15 | 1.000 | 0.953 | 1.000 | 1.000 | 21991.3 | qwen_direct:15 |
| qwen_direct:dense | SYNTHESIS | 2 | 0.000 | 0.375 | 0.667 | 1.000 | 26377.0 | qwen_direct:2 |
| qwen_direct:dense | PROCEDURAL | 2 | 0.000 | 0.300 | 1.000 | 1.000 | 18539.5 | qwen_direct:2 |
| qwen_direct:dense | JUDGMENT | 1 | 1.000 | 1.000 | 0.000 | 1.000 | 24953.0 | qwen_direct:1 |
| qwen_direct:dense | CONVERSATIONAL | 2 | 1.000 | 1.000 | 0.000 | 1.000 | 16627.5 | qwen_direct:2 |
| hierarchical:dense | DIRECT_LOOKUP | 21 | 0.952 | 0.957 | 0.881 | 1.000 | 29336.9 | hierarchical:21 |
| hierarchical:dense | COMPARATIVE | 7 | 0.857 | 0.889 | 0.762 | 1.000 | 40997.3 | hierarchical:7 |
| hierarchical:dense | CAUSAL | 15 | 1.000 | 0.960 | 0.956 | 1.000 | 38026.9 | hierarchical:15 |
| hierarchical:dense | SYNTHESIS | 2 | 0.500 | 0.575 | 0.667 | 1.000 | 53057.5 | hierarchical:2 |
| hierarchical:dense | PROCEDURAL | 2 | 1.000 | 1.000 | 0.500 | 1.000 | 17030.0 | hierarchical:2 |
| hierarchical:dense | JUDGMENT | 1 | 1.000 | 1.000 | 0.000 | 1.000 | 25211.0 | hierarchical:1 |
| hierarchical:dense | CONVERSATIONAL | 2 | 1.000 | 1.000 | 0.000 | 1.000 | 16541.0 | hierarchical:2 |
| auto:dense | DIRECT_LOOKUP | 21 | 0.809 | 0.881 | 0.897 | 1.000 | 20173.1 | qwen_direct:19, hierarchical:1, bypass:1 |
| auto:dense | COMPARATIVE | 7 | 1.000 | 0.936 | 0.905 | 1.000 | 28782.7 | qwen_direct:5, hierarchical:2 |
| auto:dense | CAUSAL | 15 | 0.933 | 0.927 | 0.967 | 1.000 | 31071.0 | qwen_direct:6, hierarchical:9 |
| auto:dense | SYNTHESIS | 2 | 0.500 | 0.425 | 0.667 | 1.000 | 52069.5 | hierarchical:2 |
| auto:dense | PROCEDURAL | 2 | 1.000 | 1.000 | 0.500 | 1.000 | 16816.0 | hierarchical:2 |
| auto:dense | JUDGMENT | 1 | 1.000 | 1.000 | 0.000 | 1.000 | 25696.0 | bypass:1 |
| auto:dense | CONVERSATIONAL | 2 | 1.000 | 1.000 | 0.000 | 1.000 | 16914.5 | bypass:2 |

## 실패 사례

- `qwen_direct:dense` / `spatial-003`: 최대 풀링은 특징 맵을 어떻게 축소하는가?
- `qwen_direct:dense` / `graph-004`: 트랜스포머와 지식 그래프를 결합한 설계가 가능한가?
- `qwen_direct:dense` / `unknown-001`: 양자 오류 정정에 surface code를 적용하는 절차는?
- `qwen_direct:dense` / `unknown-002`: 쿠버네티스에서 etcd 장애를 복구하는 명령어를 알려줘
- `qwen_direct:dense` / `unknown-003`: 반도체 식각 장비의 RF reflected power 알람 원인은?
- `qwen_direct:dense` / `unknown-004`: Rust borrow checker의 lifetime elision 규칙은?
- `qwen_direct:dense` / `unknown-005`: Redis cluster의 hash slot 재분배 방법은?
- `qwen_direct:dense` / `policy-002`: 이거 왜 그래?
- `qwen_direct:dense` / `policy-003`: 새 모델을 설계해줘
- `hierarchical:dense` / `generative-003`: GAN의 생성자와 판별자는 각각 어떤 목표를 가지는가?
- `hierarchical:dense` / `policy-002`: 이거 왜 그래?
- `hierarchical:dense` / `policy-003`: 새 모델을 설계해줘
- `auto:dense` / `backprop-004`: 역전파를 사용하지 않는 학습 방식에는 무엇이 있는가?
- `auto:dense` / `generative-002`: VAE에서 재매개변수화 트릭이 필요한 이유는?
- `auto:dense` / `unknown-004`: Rust borrow checker의 lifetime elision 규칙은?
- `auto:dense` / `unknown-005`: Redis cluster의 hash slot 재분배 방법은?
- `auto:dense` / `policy-002`: 이거 왜 그래?
- `auto:dense` / `policy-003`: 새 모델을 설계해줘
