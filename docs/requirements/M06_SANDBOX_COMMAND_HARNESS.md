# M06. Sandbox / Command Policy / agent_rule Harness

## 1. 책임

신뢰하지 않는 Repository 코드 및 LLM 실행 요청을
통제된 격리 환경에서 실행하고,
수정 정책과 명령 실행 경계를 강제한다.

---

# 2. Sandbox

기본 구조:

```text
Temporary Worktree
→ Isolated Sandbox
→ Dependency Restore
→ Test / Profiler / Benchmark
→ Result Collection
→ Dispose
```

필수 제한:

- CPU limit
- Memory limit
- execution timeout
- Internet egress BLOCK
- Repository 밖 파일 접근 제한
- writable directory 최소화
- writable storage / inode / file-count quota
- stdout / stderr / artifact output size limit
- 실행 종료 후 sandbox 폐기
- process crash 후 orphan sandbox / temp resource 식별 및 안전한 cleanup

Repository Code는 Trusted Runtime Code로 가정하지 않는다.
Sandbox process environment는 allowlist 방식으로 구성하며 Host / CLI 환경을 그대로 상속하지 않는다.

기본 차단 / 제거 대상 예:

```text
Knowledge Hub JWT / session credential
cloud provider credential
SSH_AUTH_SOCK / GPG agent socket
Host HOME credential files
package registry credential not required by runtime
arbitrary host environment secret
```

Dependency restore에 credential이 필요한 경우 restore 전용 최소 scope credential을 별도 phase에만 제공하고 Test / Profiler / Benchmark runtime으로 전달하지 않는다.
Sandbox image / volume에 production credential을 bake-in하지 않는다.

Sandbox에 제공되는 source view는 M08 Sensitive File Policy를 적용한 runtime-safe snapshot이어야 한다.

- Sensitive File은 기본적으로 Sandbox runtime에서 보이지 않게 제외한다.
- Test / Profiler / Build에 실제 민감 파일 접근이 필요한 경우 M08의 scoped `runtime-read` exception이 있어야 한다.
- runtime-read exception은 Retrieval / LLM context 또는 modification 권한을 자동으로 부여하지 않는다.
- production credential 대신 synthetic / test fixture를 사용할 수 있으면 이를 우선한다.
- Sandbox source view에는 `.git` file/directory 및 main Repository / worktree administrative metadata를 기본 노출하지 않는다. Git metadata가 테스트에 필요한 경우 sanitized read-only metadata view 또는 trusted Git proxy를 우선한다.
- Sensitive `runtime-read` 권한과 internal network allowlist를 동시에 부여하는 조합은 기본 금지하며, 불가피하면 별도의 combined exception / 최소 대상 / Audit을 요구한다.
- stdout / stderr / profiler / test artifact는 Local Store 또는 Web에 저장하기 전에 secret masking / detection을 적용한다.
- CLI / Web 표시용 텍스트는 terminal control sequence / ANSI escape / raw HTML / script-like markup을 신뢰된 UI instruction으로 해석하지 않도록 display-safe encoding / escaping을 적용한다. Raw Evidence가 필요한 경우 protected download / artifact 경로와 표시용 representation을 분리한다.
- XML / HTML / archive / structured test artifact parser는 외부 entity / template execution / path traversal 등 active-content 기능을 기본 비활성화하고 untrusted data로 처리한다.
- 안전한 redaction을 보장할 수 없는 결과는 일반 Audit payload에 저장 / 표시하지 않고 sensitive result로 격리하거나 폐기한다.

Sandbox Runtime Hardening 원칙:

- non-root 사용자 실행을 기본으로 한다.
- 불필요한 Linux capability는 제거한다.
- privilege escalation을 차단한다.
- process / PID 수를 제한한다.
- 가능한 경우 root filesystem을 read-only로 구성한다.
- Host PID / IPC / network namespace를 임의 공유하지 않는다.
- docker socket 등 Host 제어 인터페이스와 임의 Host Unix socket / device mount를 Sandbox에 노출하지 않는다.
- seccomp / AppArmor / SELinux 또는 동등한 runtime isolation policy를 적용할 수 있어야 한다.

구체적인 container runtime flag와 isolation profile은 Architecture / Detailed Design에서 확정한다.

Baseline 및 Patch Verification 실행은 검증 대상 source snapshot의 무결성을 보존해야 한다.

- 가능한 경우 source는 read-only mount / immutable snapshot으로 Sandbox에 제공한다.
- Test / Build / Profiler / Static tool이 output을 필요로 하면 source와 분리된 writable output / temp 영역을 사용한다.
- writable source copy가 불가피한 경우 실행 전후 Canonical Actual Change Set 대상 전체와 relevant source snapshot / `final_diff_hash` 기준점을 비교한다. tracked file뿐 아니라 Patch-created untracked / ignored source entry도 포함한다.
- Verification 실행으로 tracked source 또는 Patch-created untracked / ignored source entry가 변경되거나 예상 밖 source entry가 생성되면 해당 실행에서 얻은 Verification Evidence를 유효한 Patch 검증으로 사용하지 않는다.
- source mutation을 제거하고 exact verified Patch snapshot을 재구성한 뒤 Verification을 다시 수행한다.

OPTIMIZE baseline / benchmark 실행 부산물은 source Worktree와 분리한다.

- profiler / benchmark / coverage / build output은 별도 writable output directory에 기록한다.
- baseline 전후 relevant source snapshot hash를 비교하며 tracked source 외 relevant untracked source mutation도 확인한다.
- baseline 실행이 tracked source를 변경했거나 예상 밖 untracked artifact가 source diff에 혼입될 가능성이 있으면 해당 baseline Evidence를 무효화하고, reset / clean 또는 새 Worktree로 재구성한 뒤 baseline을 다시 수행한다.
- baseline 부산물을 Patch `Canonical Actual Change Set` 또는 `final_diff_hash`에 포함하지 않는다.

---

# 3. Offline Dependency Restore

허용:

```text
Prebuilt Sandbox Image
Local Package Cache
Internal PyPI / Maven / npm Mirror
Lockfile-based Existing Environment
Explicitly Allowlisted Internal Artifact Registry
```

금지:

```text
Public PyPI
Public npm Registry
Public Maven Central
GitHub Release Download
기타 Public Internet Download
```

Dependency 확보 불가 시 해당 검증은 `NOT_AVAILABLE`이 될 수 있다.

Dependency Restore와 untrusted Repository code 실행은 네트워크 경계를 분리한다.

- Dependency Restore는 Repository-controlled install / build hook을 Host 또는 일반 restore process에서 실행하지 않는 별도 restore phase 또는 동등한 통제 경로를 사용한다.
- prebuilt wheel / image / cache를 우선하며, dependency 자체의 build / install code 실행이 불가피한 경우 source Repository / credential을 마운트하지 않은 별도 dependency-builder sandbox에서 최소 권한으로 실행한다.
- Repository 자체의 install / build hook이 검증에 필수인 경우 dependency restore와 분리된 untrusted project sandbox에서 실행하고, 기본적으로 network egress 없이 수행한다.
- Internal package / artifact mirror 접근이 필요한 경우 restore / dependency-builder phase에만 최소 allowlist를 부여한다.
- Test / Profiler / Benchmark 등 untrusted runtime execution은 restore phase의 registry / artifact network 권한을 자동 상속하지 않는다.
- runtime 단계의 network는 기본 `NONE / BLOCK`이며, 테스트 자체에 내부 서비스 접근이 필요한 경우 별도의 명시적 allowlist와 Audit을 요구한다.
- Internal network allowlist는 단순 connectivity permission이지 임의 source / artifact 전송 권한이 아니다. 가능하면 synthetic / isolated test endpoint를 사용하고 destination / protocol / port / data-egress scope를 최소화하며, production control plane이나 범용 upload endpoint를 기본 허용하지 않는다.
- submodule dependency가 필요한 경우 자동 init / remote fetch를 기본 금지하고, pre-populated local submodule 또는 explicitly allowlisted internal source만 Safe Git profile / isolated restore 경로로 준비한다.
- required Verification 환경은 lockfile / resolved dependency set / artifact source(origin) / 가능하면 artifact digest 또는 동등한 immutable identifier를 기록하여 동일 version name의 mutable artifact를 조용히 동일 환경으로 취급하지 않는다.
- lockfile 없이 floating/latest resolution이 필요한 경우 이를 reproducibility limitation으로 기록하고 required Verification의 재현성을 보장할 수 없으면 `NOT_AVAILABLE` 또는 `INCONCLUSIVE`로 처리할 수 있어야 한다.

---

# 4. Command Execution Policy

LLM은 raw shell 명령을 직접 실행하지 않는다.
Repository source / comment / README / test output / profiler output 내부의 instruction-like text는 Tool permission 또는 policy authority로 취급하지 않는다. 이러한 Evidence에서 생성된 Tool Request도 동일한 Command Policy / Guardrail / Sandbox 경계를 통과해야 한다.

Tool 실행은 신뢰 경계에 따라 두 클래스로 분리한다.

```text
Qwen
→ Tool Request
→ Command Policy
   ├─ Trusted Non-Executing Adapter
   │    └─ Safe Git status / diff / repository introspection, pure source parser 등
   └─ Untrusted / Project-Aware Tool
        └─ Isolated Sandbox
```

Trusted Adapter는 Host에서 동작할 수 있지만 repository-controlled hook / filter / plugin / external command를 실행하지 않는 Safe Git / read-only profile이어야 한다.
Repository code / build hook / plugin 실행 가능성이 있는 도구는 Trusted Adapter로 분류하지 않는다.
Trusted Non-Executing Adapter도 untrusted filename / source / graph input을 처리하므로 configurable input-size / file-count / execution-time / memory bound와 fail-safe parser policy를 가져야 한다. 비실행 도구라는 이유만으로 Host resource exhaustion에 무제한 노출하지 않는다.

허용 후보:

```text
Trusted Safe-Git Adapter: git status / diff / change-set inspection
Canonical Change Set whitespace validator
python -m pytest
pytest
ruff
mypy
coverage
cProfile wrapper
tracemalloc wrapper
pre-registered project test command
pre-registered project build command
```

기본 차단 후보:

```text
sudo
ssh
scp
curl
wget
nc
rm -rf
mkfs
mount
docker socket direct access
host package manager mutation
arbitrary outbound network command
```

추가 원칙:

- Guardrail / Command allowlist / Sandbox capability / Network allowlist / Sensitive exception / policy compatibility와 같은 권한 부여 정책은 untrusted Repository source 또는 LLM output이 직접 self-authorize할 수 없다. Authority-bearing policy는 Repository 밖 trusted local policy store, signed/admin-controlled configuration 또는 동등한 보호 경계에서 관리한다.
- Repository 내부 config는 project test/build command, language metadata 등을 제안할 수 있으나 그 내용만으로 Host execution, network, credential, sensitive access, policy exception 권한을 확대하지 않는다. 권한 확대는 별도의 trusted registration / authorization을 요구한다.
- Repository code / project plugin / build hook을 실행할 가능성이 있는 Static Analysis / LSP / formatter / build-tool inspection도 M06 Command Policy / Sandbox 경로를 사용한다.
- Safe Git / pure source parsing처럼 repository-controlled executable integration을 완전히 차단한 도구만 Trusted Non-Executing Adapter로 Host 실행을 허용할 수 있다.
- Trusted Safe-Git Adapter는 object alternates / promisor / replace-ref 등 Repository object source를 trusted policy로 제한하고, status/diff/introspection 중 missing object를 이유로 임의 network fetch를 수행하지 않는다.
- 순수 source parsing처럼 Repository code를 실행하지 않는 분석은 read-only 도구로 분리할 수 있다.
- path argument는 canonicalize / realpath 검증 후 허용된 Repository / output root 내부인지 확인하고 symlink / junction escape를 차단
- hardlink / bind mount / mount-point / reparse-point 등 path canonicalization만으로 드러나지 않는 aliasing을 통해 Repository / Sandbox root 밖 protected object에 접근하거나 write하지 못하도록 filesystem identity / mount boundary를 검증하고, 안전성을 증명할 수 없으면 fail-closed
- 별도 ACL이 확인되지 않은 nested Repository / submodule working tree는 parent Repository Sandbox source view에 자동 포함하지 않음
- path list / Git change output은 structured / NUL-safe representation으로 전달하고, filename을 shell option / newline-delimited command fragment로 재해석하지 않는다. subprocess에 path를 전달할 때 option terminator 또는 동등한 API boundary를 사용한다.
- command + args 구조화
- raw shell string 금지
- shell metacharacter / command chaining / substitution 기본 차단
- project command는 pre-registered template만 허용
- command / args / exit code / duration은 Audit 기록
- Guardrail / Command Policy / Sandbox execution에는 사용한 `policy_version / command_policy_version / sandbox_profile_version` 또는 동등한 버전 식별자를 기록
- secret은 마스킹

---

# 5. agent_rule Harness

Guardrail은 Patch 적용 전과 Canonical Actual Change Set 생성 후 두 단계로 적용한다.

## Pre-Apply Guardrail

```text
Evidence First
→ lite / full policy
→ Minimum Change
→ Proposed Patch Inspection
→ Pre-Apply Guardrail
   ├─ ALLOW → M05 Worktree Apply
   └─ BLOCK → Worktree Apply 금지 / Audit 기록
```

Worktree 적용 전에 최소 다음을 검사한다.

- unresolved merge conflict
- `.env` 및 sensitive path 대상 변경 (M08의 scoped explicit modification exception이 없는 경우 기본 차단)
- `.git` / Git worktree administrative metadata 등 Repository control metadata 대상 변경
- Knowledge Hub의 authority-bearing local policy / credential / control-plane configuration을 Patch target으로 가장하거나 Repository path alias를 통해 수정하려는 변경
- FIFO / device / socket 등 기본 지원하지 않는 special filesystem object 생성
- credential / private key / token 등 민감 파일 대상 변경 (동일한 M08 정책 적용)
- 명백한 secret pattern 추가 (명시적 scoped exception이 없는 경우 기본 차단)
- 금지된 파일 경로 / 변경 범위
- Worktree / Host resource quota를 초과하는 patch bytes / file count / single-file size / path count
- 기존 symlink / junction / hardlink / mount / reparse-point 또는 Patch 내부 operation ordering을 이용해 canonical Worktree root 밖이나 보호 대상 object에 side effect를 전달하려는 target / ancestor path
- 별도 Repository identity / ACL이 확인되지 않은 nested Repository / submodule working tree 내부를 수정하려는 target (parent Repository의 gitlink metadata 변경은 별도 정책으로 판정)
- `sensitive_provenance`가 있는 Patch가 기존 보호 수준보다 낮은 일반 source / output 경계로 derived content를 이동시키는 경우 scoped declassification decision 존재 여부
- 정책상 허용되지 않은 대규모 또는 destructive change

Pre-Apply Guardrail에서 차단된 Patch는 Temporary Worktree에 적용하지 않는다.
차단은 `PATCH_APPLY_FAILED`와 구분하며, Patch 적용 시도 전 정책 차단으로 Audit에 기록한다.

Sensitive File modification은 기본 `BLOCK`이다.
예외는 M08이 승인한 explicit local policy exception이 현재 `user / repository / path / operation / policy version / expiry` 범위를 정확히 포함하고 실행 시점에도 유효할 때만 인정할 수 있고, 사용 사실을 M09 Audit에 기록한다.
Sensitive File modification exception은 해당 파일의 raw content를 Retrieval / LLM context에 포함할 권한을 자동으로 부여하지 않는다.
`sensitive_provenance`가 붙은 plan / patch / derived artifact를 일반 non-sensitive destination에 기록하는 것은 보호경계 downgrade가 될 수 있으므로, M08이 정의한 destination classification 또는 scoped `declassify` decision 없이 자동 허용하지 않는다. 동일 보호 범위 내에서 provenance를 유지하는 경우에는 declassification으로 간주하지 않을 수 있다.

## Post-Apply Diff Guardrail

```text
M05 Worktree Apply
→ Canonical Actual Change Set
→ Post-Apply Diff Guardrail
→ Command Policy
→ Test / Profiler / Benchmark
→ Verification
```

Canonical Actual Change Set 기준으로 최소 다음을 다시 확인한다.

- whitespace error
- 민감 파일 변경 여부 및 적용된 M08 scoped exception의 유효성
- secret pattern 유입 여부 및 허용 범위 초과 여부
- unresolved conflict marker
- Proposed Patch와 Canonical Actual Change Set 사이의 예상 밖 변경
- 새 / untracked / ignored Patch-created file 및 mode / symlink / gitlink 변경의 정책 위반 여부
- 허용된 Repository / Sandbox root 밖을 가리키는 symlink 또는 path traversal 위험
- `sensitive_provenance` derived content가 lower-protection destination으로 이동했는데 required declassification / reclassification policy decision이 없는 경우
- Canonical Actual Change Set 생성 실패 / 불완전 상태에서는 Guardrail을 성공으로 간주하지 않음

Pre-Apply 검사를 통과했더라도 Canonical Actual Change Set이 정책을 위반하면 Verification 실행을 차단하고 Audit에 기록한다.

---

# 6. 의존 모듈

- M05 Worktree
- M07 Verification Plan
- M08 Security
- M09 Audit

---

# 7. 성공 기준

- Test / Profiler / Benchmark가 Host에서 직접 실행되지 않는다.
- Host에서 허용되는 Git / source inspection은 Trusted Non-Executing Adapter에 한정되고 repository-controlled executable integration을 실행하지 않는다.
- Repository code / project plugin / build hook 실행 가능성이 있는 Static Analysis / LSP도 Host에서 직접 실행되지 않는다.
- CPU / Memory / execution timeout과 writable storage / inode / output size 제한이 실제 Sandbox 실행에 적용된다.
- 외부 egress가 기본 차단된다.
- Sandbox에서 허용된 Repository 범위 밖의 파일 접근이 차단된다.
- writable directory가 허용된 최소 범위로 제한된다.
- Public dependency download가 차단되고, dependency restore용 allowlist가 untrusted runtime 단계에 자동 상속되지 않는다.
- required Verification dependency의 lockfile / resolved origin / artifact digest-or-equivalent provenance를 기록하여 mutable dependency resolution을 조용히 동일 환경으로 취급하지 않는다.
- Trusted Non-Executing Adapter도 bounded resource / safe parser policy로 untrusted input을 처리한다.
- 실행 종료 후 Sandbox를 폐기할 수 있고 crash 후 orphan Sandbox도 active execution과 구분해 안전하게 정리할 수 있다.
- LLM 임의 shell 실행이 불가능하다.
- Repository source / config 또는 Patch가 Guardrail / Command / Sandbox / Network / Sensitive exception authority를 self-authorize하여 권한을 확대할 수 없다.
- Repository / tool output의 prompt injection 또는 instruction-like content가 Command Policy / Guardrail / Security Policy를 변경하거나 우회할 수 없다.
- 허용되지 않은 command를 차단한다.
- 민감 파일 수정 요청은 기본적으로 Worktree 적용 전 Pre-Apply Guardrail에서 차단하며, M08의 scoped explicit exception만 제한적으로 인정한다.
- Sensitive File은 Sandbox runtime에서 기본 비가시화하고, scoped `runtime-read` exception 없이 untrusted Repository code가 읽을 수 없게 한다.
- Host / CLI credential과 임의 environment secret이 untrusted Sandbox runtime으로 상속되지 않는다.
- stdout / stderr / profiler / test output에 포함된 secret이 일반 Audit / Web output으로 원문 노출되지 않도록 통제한다.
- Sensitive runtime-read와 network allowlist 같은 고위험 권한 조합은 각각의 개별 예외만으로 자동 결합하지 않는다.
- Sandbox runtime이 main Repository의 writable `.git` / worktree administrative metadata를 직접 조작할 수 없게 한다.
- Canonical Actual Change Set을 Post-Apply Diff Guardrail에서 재검사할 수 있다.
- Guardrail / Command / Sandbox 결과에 적용된 정책 / profile version을 추적할 수 있다.
- Sandbox가 non-root / least-privilege 원칙과 Host isolation 정책을 강제할 수 있다.
- path / symlink / junction / hardlink / mount / reparse alias를 통한 Repository / Sandbox root 밖 접근·write 우회를 차단하거나 안전성을 증명할 수 없으면 fail-closed 처리한다.
- 별도 ACL이 확인되지 않은 nested Repository / submodule working tree를 parent Repository 권한만으로 Sandbox source / Patch target에 포함하지 않는다.
- OPTIMIZE baseline 부산물이 tracked / relevant untracked source 또는 Patch Change Set을 오염시키지 않도록 검출 / 정리할 수 있다.
- Patch Verification 실행 전후 Canonical Actual Change Set 전체 / source snapshot / final diff integrity를 확인하고, 검증 도구가 tracked 또는 Patch-created untracked source를 변경하면 해당 Verification Evidence를 폐기 / 재실행할 수 있다.
