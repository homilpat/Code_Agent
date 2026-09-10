'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Header from '@/components/layout/Header';
import Footer from '@/components/layout/Footer';
import type { ConversationTurn } from '@/components/AiKnowledgeChat';
import { authFetch, getUser } from '@/lib/auth-client';

type SavedConversation = {
  id: number;
  title: string;
  conversationJson: string;
  createdAt: string;
  updatedAt: string;
};

function parseTurns(value: string): ConversationTurn[] {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function sourceUrl(source: ConversationTurn['sources'][number]) {
  if (source.sourceType === 'WEB' && source.url && /^https?:\/\//i.test(source.url)) return source.url;
  return source.url && /^\/posts\/\d+$/.test(source.url) ? source.url : `/posts/${source.sourceId}`;
}

export default function ConversationsPage() {
  const [items, setItems] = useState<SavedConversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');

  async function load() {
    if (!getUser()) {
      setMessage('저장된 대화를 보려면 로그인해주세요.');
      setLoading(false);
      return;
    }
    try {
      const response = await authFetch('/api/conversations');
      if (!response.ok) throw new Error();
      setItems(await response.json());
    } catch {
      setMessage('대화 기록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function remove(id: number) {
    if (!confirm('이 대화 기록을 삭제할까요?')) return;
    const response = await authFetch(`/api/conversations/${id}`, { method: 'DELETE' });
    if (response.ok) setItems((current) => current.filter((item) => item.id !== id));
    else setMessage('대화 기록을 삭제하지 못했습니다.');
  }

  return <div className="portal-page"><Header/><main className="portal-main">
    <div className="mb-7"><span className="mono text-[11px] text-[#06b6d4]">PRIVATE AI NOTEBOOK</span><h1 className="mt-2 text-3xl font-bold text-[#002045]">지식창고와의 대화</h1><p className="mt-2 text-sm text-[#545f72]">직접 기록한 대화만 사용자별로 보관됩니다. 저장된 AI 답변은 RAG 지식으로 색인되지 않습니다.</p></div>
    {message && <div className="panel mb-5 p-4 text-sm text-[#545f72]">{message}{!getUser() && <Link href="/auth" className="ml-3 font-bold text-blue-700">로그인하기 →</Link>}</div>}
    {loading ? <div className="panel py-16 text-center mono text-sm text-[#545f72]">LOADING CONVERSATIONS...</div> : items.length === 0 ? <div className="panel py-16 text-center"><p className="text-[#545f72]">기록한 대화가 없습니다.</p><Link href="/#ai-search" className="btn-primary mt-5 inline-block">AI와 대화하기</Link></div> : <div className="space-y-5">{items.map((item) => {
      const turns = parseTurns(item.conversationJson);
      return <article key={item.id} className="panel p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-bold text-[#002045]">{item.title}</h2><p className="mt-1 mono text-[10px] text-[#667080]">{new Date(item.updatedAt || item.createdAt).toLocaleString('ko-KR')} · {turns.length}개 질문</p></div><button type="button" onClick={() => remove(item.id)} className="btn-secondary text-xs">기록 삭제</button></div><div className="mt-6 space-y-7">{turns.map((turn, index) => <section key={index} className="border-t border-[#e0e3e5] pt-5"><div className="ml-auto max-w-[85%] rounded bg-[#eaf1f8] px-4 py-3 text-sm font-semibold text-[#002045]">{turn.query}</div><div className="mt-4 whitespace-pre-wrap text-sm leading-7 text-[#43474e]">{turn.answer}</div>{turn.sources?.length > 0 && <div className="mt-4 flex flex-wrap gap-2">{turn.sources.map((source) => <Link key={`${source.sourceId}-${source.chunkIndex}`} href={sourceUrl(source)} target="_blank" rel="noopener noreferrer" className="rounded border border-[#8bdbe7] bg-[#eaf8fa] px-3 py-2 mono text-[11px] font-bold text-[#007d91] hover:border-[#002045] hover:text-[#002045]">근거 {source.citationNumber} · {source.title}</Link>)}</div>}</section>)}</div></article>;
    })}</div>}
  </main><Footer/></div>;
}
