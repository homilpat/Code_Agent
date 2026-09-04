'use client';

import Link from 'next/link';
import { FormEvent, ReactNode, useState } from 'react';
import { API_URL } from '@/lib/knowledge-api';
import { authFetch, getUser } from '@/lib/auth-client';

export type ConversationSource = {
  sourceId: number;
  title: string;
  url?: string;
  snippet: string;
  score: number;
  chunkIndex: number;
  citationNumber: number;
};

export type ConversationTurn = {
  query: string;
  answer: string;
  sources: ConversationSource[];
  responseTimeMs?: number;
  intent?: string;
  coverage?: string;
  retrievalMode?: string;
  generationMode?: string;
  selectedCitationCount?: number;
  missingPoints?: string[];
  trace?: { name: string; status: string; latencyMs: number; detail?: string }[];
};

function sourceUrl(source: ConversationSource) {
  return source.url && /^\/posts\/\d+$/.test(source.url) ? source.url : `/posts/${source.sourceId}`;
}

function AnswerWithEvidenceButtons({ turn }: { turn: ConversationTurn }) {
  const parts = turn.answer.split(/(\[근거\s+\d+\])/g);
  return <div className="whitespace-pre-wrap text-sm leading-7 text-[#43474e]">{parts.map((part, index): ReactNode => {
    const match = part.match(/^\[근거\s+(\d+)\]$/);
    if (!match) return <span key={index}>{part}</span>;
    const source = turn.sources.find((item) => item.citationNumber === Number(match[1]));
    if (!source) return <span key={index}>{part}</span>;
    return <button key={index} type="button" onClick={() => window.open(sourceUrl(source), '_blank', 'noopener,noreferrer')} className="mx-1 inline-flex items-center rounded border border-[#8bdbe7] bg-[#eaf8fa] px-2 py-0.5 mono text-[11px] font-bold text-[#007d91] hover:border-[#002045] hover:text-[#002045]" title={`${source.title} 원문 열기`}>{part}</button>;
  })}</div>;
}

export default function AiKnowledgeChat() {
  const [query, setQuery] = useState('');
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedConversationId, setSavedConversationId] = useState<number | null>(null);
  const [message, setMessage] = useState('');

  async function ask(event: FormEvent) {
    event.preventDefault();
    const nextQuery = query.trim();
    if (!nextQuery || loading) return;
    setLoading(true);
    setMessage('');
    try {
      const history = turns.flatMap((turn) => [
        { role: 'user', content: turn.query },
        { role: 'assistant', content: turn.answer },
      ]).slice(-6);
      const response = await fetch(`${API_URL}/api/rag/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: nextQuery, domainFilter: null, topK: 6, history }),
      });
      if (!response.ok) throw new Error();
      const data = await response.json();
      setTurns((current) => [...current, {
        query: nextQuery,
        answer: data.answer,
        sources: data.sources || [],
        responseTimeMs: data.responseTimeMs,
        intent: data.intent,
        coverage: data.coverage,
        retrievalMode: data.retrievalMode,
        generationMode: data.generationMode,
        selectedCitationCount: data.selectedCitationCount,
        missingPoints: data.missingPoints || [],
        trace: data.trace || [],
      }]);
      setQuery('');
    } catch {
      setMessage('지식 검색 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      setLoading(false);
    }
  }

  async function saveConversation() {
    if (!turns.length || saving) return;
    if (!getUser()) {
      setMessage('대화를 기록하려면 먼저 로그인해주세요.');
      return;
    }
    setSaving(true);
    setMessage('대화를 기록하고 있습니다...');
    try {
      const response = await authFetch(savedConversationId ? `/api/conversations/${savedConversationId}` : '/api/conversations', {
        method: savedConversationId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: turns[0].query.slice(0, 80),
          conversationJson: JSON.stringify(turns),
        }),
      });
      if (response.status === 401) {
        setMessage('로그인이 만료되었습니다. 다시 로그인해주세요.');
      } else if (!response.ok) {
        setMessage(`대화 기록에 실패했습니다. (${response.status})`);
      } else {
        const saved = await response.json();
        setSavedConversationId(saved.id);
        setMessage('`지식창고와의 대화`에 기록했습니다. AI 답변은 RAG에 색인되지 않습니다.');
      }
    } catch {
      setMessage('대화 기록 서버에 연결할 수 없습니다.');
    } finally {
      setSaving(false);
    }
  }

  return <section id="ai-search" className="panel relative overflow-hidden p-6">
    <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-[#06b6d4] to-[#002045]"/>
    <div className="mb-4 flex flex-wrap items-center gap-2"><span className="text-2xl text-[#06b6d4]">▣</span><h2 className="text-lg font-bold text-[#002045]">AI Knowledge Retrieval</h2>{turns.length > 0 && <div className="ml-auto flex gap-2"><button type="button" onClick={() => { setTurns([]); setSavedConversationId(null); setMessage(''); }} className="btn-secondary text-xs">새 대화</button><button type="button" onClick={saveConversation} disabled={saving} className="btn-primary text-xs disabled:opacity-50">{saving ? '기록 중...' : savedConversationId ? '대화 기록 업데이트' : '대화 기록하기'}</button></div>}</div>
    <form onSubmit={ask} className="flex gap-3"><div className="relative flex-1"><input value={query} onChange={(event) => setQuery(event.target.value)} className="field h-12" placeholder="기술 문제를 설명하거나 저장된 지식에 대해 질문하세요..."/></div><button disabled={loading} className="btn-ai flex h-12 shrink-0 items-center gap-2 disabled:opacity-50">✦ {loading ? '근거 검증 중...' : 'Ask AI'}</button></form>
    {message && <p className="mt-3 mono text-xs text-[#008aa3]">{message}</p>}
    {turns.length > 0 && <div className="mt-5 space-y-7 border-t border-[#e0e3e5] pt-5">{turns.map((turn, turnIndex) => <article key={turnIndex} className="space-y-4"><div className="ml-auto max-w-[85%] rounded bg-[#eaf1f8] px-4 py-3 text-sm font-semibold text-[#002045]">{turn.query}</div><AnswerWithEvidenceButtons turn={turn}/><details className="border border-[#d8dde5] bg-[#f8fafc] px-4 py-3 text-xs"><summary className="cursor-pointer font-bold text-[#1a365d]">처리 과정 · {turn.coverage || 'UNKNOWN'} · {turn.responseTimeMs ? `${(turn.responseTimeMs / 1000).toFixed(1)}초` : '측정 없음'}</summary><div className="mt-3 flex flex-wrap gap-2 mono text-[10px] text-[#455f88]"><span className="border px-2 py-1">INTENT {turn.intent || '-'}</span><span className="border px-2 py-1">RETRIEVAL {turn.retrievalMode || 'dense'}</span><span className="border px-2 py-1">GENERATION {turn.generationMode || 'hierarchical'}</span><span className="border px-2 py-1">EVIDENCE {turn.selectedCitationCount ?? turn.sources.length}</span></div>{turn.missingPoints && turn.missingPoints.length > 0 && <div className="mt-3 border-l-2 border-amber-400 pl-3 text-[#6b4f00]"><b>확인되지 않은 항목</b><ul className="mt-1 list-disc pl-4">{turn.missingPoints.map((item) => <li key={item}>{item}</li>)}</ul></div>}{turn.trace && turn.trace.length > 0 && <ol className="mt-3 space-y-2">{turn.trace.map((step, index) => <li key={`${step.name}-${index}`} className="flex items-start justify-between gap-3 border-t border-[#e0e3e5] pt-2"><span><b>{index + 1}. {step.name}</b>{step.detail && <span className="ml-2 text-[#667080]">{step.detail}</span>}</span><span className="mono shrink-0">{step.latencyMs}ms</span></li>)}</ol>}</details>{turn.sources.length > 0 && <section><h3 className="mono mb-3 text-xs font-bold text-[#002045]">ANSWER EVIDENCE · {turn.sources.length}</h3><div className="grid gap-3 md:grid-cols-2">{turn.sources.map((source) => <article key={`${source.sourceId}-${source.chunkIndex}`} className="border border-[#c4c6cf] bg-[#f7f9fb] p-4 text-xs text-[#1a365d]"><Link href={sourceUrl(source)} target="_blank" rel="noopener noreferrer" className="flex w-full items-start justify-between gap-3 rounded border border-[#8bdbe7] bg-[#eaf8fa] px-3 py-2 text-left hover:border-[#002045]"><b>근거 {source.citationNumber} · {source.title}</b><span className="mono shrink-0">{(source.score * 100).toFixed(1)}%</span></Link><blockquote className="mt-3 border-l-2 border-[#06b6d4] pl-3 leading-5 text-[#43474e]">{source.snippet}</blockquote></article>)}</div></section>}</article>)}</div>}
  </section>;
}
