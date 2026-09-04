import logging
import re
from typing import List

from app.services.query_planner import QueryPlan

logger = logging.getLogger(__name__)


class ClaimJudge:
    _LEADING_CITATIONS = re.compile(
        r"^(?P<prefix>\s*(?:(?:[-*]|\d+\.)\s+)?)"
        r"(?P<cites>\[근거\s+\d+\](?:\s*(?:와|과|,)\s*\[근거\s+\d+\])*)"
        r"\s*(?:에서는|에서|은|는|에 따르면)\s*"
    )

    @staticmethod
    def _complete(llm_client, model: str, messages):
        last_error = None
        for attempt in range(2):
            try:
                return llm_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
                )
            except Exception as error:
                last_error = error
                logger.warning("Claim verification attempt %d failed: %s", attempt + 1, error)
        raise last_error

    @staticmethod
    def keep_cited_claims(answer: str) -> str:
        """Keep grounded blocks without fragmenting natural multi-sentence paragraphs."""
        cleaned_lines: List[str] = []
        for line in answer.splitlines():
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append("")
                continue
            if stripped.startswith("#") or re.fullmatch(r"[-*_]{3,}", stripped):
                cleaned_lines.append(line)
                continue

            # One citation may support a short paragraph containing several connected
            # sentences. Sentence-level deletion made otherwise valid prose fragmentary.
            if re.search(r"\[근거\s+\d+\]", stripped):
                cleaned_lines.append(line)
                continue

            # Explicitly marked recommendations and uncertainty are not source facts.
            # The verifier separately prevents them from introducing unsupported
            # technical claims, metrics, or named methods.
            if re.match(r"^(제안|다음 단계|검증|주의|한계)\s*:", stripped):
                cleaned_lines.append(line)

        cleaned = "\n".join(cleaned_lines).strip()
        return cleaned or "검색된 원문을 직접 인용해 답변을 구성하지 못했습니다. 출처 목록을 확인해주세요."

    @classmethod
    def naturalize_citations(cls, answer: str) -> str:
        """Move citation-led evidence narration to the end of each sentence."""
        natural_lines: List[str] = []
        for line in answer.splitlines():
            parts = re.split(r"(?<=[.!?。])(?=\s+)", line)
            rewritten_parts: List[str] = []
            for part in parts:
                match = cls._LEADING_CITATIONS.match(part)
                if not match:
                    rewritten_parts.append(part)
                    continue

                citations = "".join(re.findall(r"\[근거\s+\d+\]", match.group("cites")))
                body = part[match.end():].strip()
                if not body:
                    continue
                if body[-1:] in ".!?。":
                    body = f"{body[:-1].rstrip()} {citations}{body[-1]}"
                else:
                    body = f"{body} {citations}"
                rewritten_parts.append(match.group("prefix") + body)
            natural_lines.append("".join(rewritten_parts))
        return "\n".join(natural_lines).strip()

    def verify(
        self,
        llm_client,
        model: str,
        plan: QueryPlan,
        context_text: str,
        draft_answer: str,
        extra_instructions: str = "",
    ) -> str:
        # Let the verifier see the coherent draft. Removing individual sentences
        # before verification caused it to reconstruct a stiff evidence report.
        grounded_draft = draft_answer
        system_prompt = (
            "당신은 RAG 답변의 엄격한 근거 검증 편집자입니다. 초안의 각 주장을 참고 원문과 대조해 최종 답변을 다시 쓰세요. "
            "인용 번호가 있다는 사실만으로 근거가 충분하다고 간주하지 말고, 해당 원문이 주장의 기술 용어와 전제를 실제로 지지하는지 확인하세요. "
            "직접 근거가 있는 사실은 유지하고, 보수적으로 도출 가능한 추론은 필요한 경우에만 '근거를 종합하면' 또는 '추론하면'이라고 한 번 표시하세요. "
            "원문에 없는 수치·실험 결과·구체적 우열·성공 보장·새로운 기술 사실은 삭제하세요. "
            "연산 방식이 복잡하다는 사실만으로 대규모 데이터셋이나 고성능 컴퓨팅 자원이 필수라고 추정하지 마세요. 그런 요구 조건은 원문에 직접 있을 때만 유지하세요. "
            "영문 기술명과 고유명사는 참고 원문에 적힌 표기를 글자 단위로 그대로 복사하고 번역·음역·철자 변형을 하지 마세요. "
            "질문에 대한 직접 답변을 첫 1~2문장에 제시하고, 사실 주장이 있는 문단이나 항목 끝에 정확한 [근거 N]을 붙이세요. "
            "출처를 번호순으로 요약하지 말고 여러 근거를 하나의 논리적인 설명으로 종합하세요. "
            "초안에 등장했다는 이유만으로 모든 근거를 유지하지 말고, 질문에 직접 필요한 주장과 근거만 남기세요. "
            "'[근거 N]에서는'처럼 인용 번호를 문장의 주어로 사용하지 마세요. "
            "'직접 답변:', '근거 기반 설명:', '기술적 가능성:' 같은 고정된 보고서형 섹션을 만들지 말고, 질문이 요구할 때만 짧은 목록을 사용하세요. "
            "실행 조언은 '제안:' 또는 '다음 단계:'로 명시하면 인용 없이 제시할 수 있지만, 원문에 없는 기술명·수치·성능 주장을 새로 넣어서는 안 됩니다. "
            "각 문단이 새로운 정보를 추가하는지 확인하고, 이미 말한 결론이나 제안을 표현만 바꿔 반복한 문단은 삭제하세요. "
            "근거의 직접 언급이 없다는 경고를 반복하거나 그것으로 답변을 끝내지 마세요. "
            + extra_instructions
        )
        response = self._complete(
            llm_client=llm_client,
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"참고 원문:\n{context_text}\n\n"
                        f"질문:\n{plan.original_query}\n\n"
                        f"1차 근거 검사를 통과한 답변:\n{grounded_draft}"
                    ),
                },
            ],
        )
        verified = response.choices[0].message.content or grounded_draft
        grounded = self.keep_cited_claims(verified)
        return self.naturalize_citations(grounded)

    def validate_citations(self, answer: str, valid_citations: set[int]) -> str:
        """Apply deterministic citation checks after the final answer model."""
        cleaned = re.sub(
            r"\[근거\s+(\d+)\]",
            lambda match: (
                match.group(0) if int(match.group(1)) in valid_citations else ""
            ),
            answer,
        )
        return self.naturalize_citations(self.keep_cited_claims(cleaned))

    @staticmethod
    def quality_issues(
        answer: str,
        valid_citations: set[int],
        require_citation: bool = True,
        require_partial_disclosure: bool = False,
    ) -> List[str]:
        """Return deterministic reasons that make a generated answer unsafe to ship."""
        stripped = answer.strip()
        if not stripped:
            return ["답변이 비어 있습니다."]

        issues: List[str] = []
        citations = [int(number) for number in re.findall(r"\[근거\s+(\d+)\]", stripped)]
        invalid = sorted(set(citations) - valid_citations)
        if invalid:
            issues.append(f"선택되지 않은 근거 번호가 있습니다: {invalid}")
        if require_citation and not any(number in valid_citations for number in citations):
            issues.append("선택된 원문을 가리키는 유효한 인용이 없습니다.")
        if re.match(r"^[,，;；:]", stripped):
            issues.append("답변이 잘못된 문장부호로 시작합니다.")
        if "```" in stripped or re.match(r"^\s*[{\[]", stripped):
            issues.append("사용자 답변 대신 코드 블록이나 구조화 데이터가 출력되었습니다.")
        if re.search(r"\b(?:answer_focus|selected_citations|missing_points|coverage)\b", stripped):
            issues.append("내부 구조화 필드가 노출되었습니다.")
        if require_partial_disclosure and not re.search(
            r"근거.{0,12}(?:부족|없|확인)|(?:판단|확인).{0,12}(?:어렵|없)|자료.{0,12}부족",
            stripped,
        ):
            issues.append("부분 근거 상태인데 확인할 수 없는 범위를 밝히지 않았습니다.")

        paragraphs = [
            re.sub(r"\s+", " ", paragraph).strip().casefold()
            for paragraph in re.split(r"\n\s*\n", stripped)
            if paragraph.strip()
        ]
        if len(paragraphs) != len(set(paragraphs)):
            issues.append("동일한 문단이 반복되었습니다.")
        return issues


claim_judge = ClaimJudge()
