'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Header from '@/components/layout/Header';
import Footer from '@/components/layout/Footer';
import AiKnowledgeChat from '@/components/AiKnowledgeChat';
import { API_URL, Category, FALLBACK_CATEGORIES, fetchCategories } from '@/lib/knowledge-api';
import { authFetch } from '@/lib/auth-client';

type Post = {
  id: number;
  title: string;
  summary?: string;
  keyPoints?: string;
  learningDirections?: string;
  content: string;
  tags?: string;
  categoryName?: string;
  categorySection?: string;
  createdAt: string;
  isIndexedInRag?: boolean;
};

type LearningRecommendation = {
  id: string;
  topic: string;
  reason: string;
  evidenceStatus: 'INTERNAL' | 'WEB' | 'IDEA';
  citationNumbers: number[];
  checked?: boolean;
};

type LearningSource = {
  citationNumber: number;
  sourceType: 'INTERNAL' | 'WEB';
  sourceId?: number;
  title: string;
  url: string;
  publisher: string;
  snippet: string;
  checkedAt?: string;
};

type LearningDirectionResult = {
  recommendations: LearningRecommendation[];
  sources: LearningSource[];
  retrievalMode?: string;
  webSearchUsed?: boolean;
  responseTimeMs?: number;
};

const tagColors: Record<string, string> = {
  PROCESS: 'bg-sky-100 text-sky-800 border-sky-200',
  EQUIPMENT: 'bg-indigo-100 text-indigo-800 border-indigo-200',
  TROUBLESHOOT: 'bg-amber-100 text-amber-800 border-amber-200',
  YIELD_METRO: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  AI_TECH: 'bg-purple-100 text-purple-800 border-purple-200',
  PROJECT_LOG: 'bg-slate-100 text-slate-700 border-slate-200',
};

function PostCard({ post }: { post: Post }) {
  return <Link href={`/posts/${post.id}`} aria-label={`${post.title} 원문 보기`} className="panel group flex min-h-60 flex-col p-5 hover:border-[#002045] focus:outline-none focus:ring-2 focus:ring-[#06b6d4]">
    <div className="flex items-start justify-between gap-3"><div className="flex flex-wrap items-center gap-2"><span className={`border px-2 py-1 mono text-[11px] ${tagColors[post.categorySection || ''] || 'bg-slate-100 text-slate-700'}`}>{post.categoryName || '미분류'}</span>{post.tags && <span className="mono text-[11px] text-[#545f72]">{post.tags}</span>}</div><span className={`mt-1 h-2 w-2 rounded-full ${post.isIndexedInRag ? 'bg-emerald-500' : 'bg-amber-500'}`} title={post.isIndexedInRag ? 'RAG indexed' : 'Index pending'}/></div>
    <h2 className="mt-4 text-xl font-bold text-[#002045] group-hover:text-blue-700">{post.title}</h2>
    <p className="mt-3 line-clamp-3 flex-1 text-sm leading-6 text-[#43474e]">{post.summary || '요약이 생성되지 않았습니다.'}</p>
    <div className="mt-5 flex items-center justify-between border-t border-[#e0e3e5] pt-4"><span className="mono text-[11px] text-[#545f72]">▤ {post.createdAt ? new Date(post.createdAt).toLocaleDateString('ko-KR') : 'KNOWLEDGE POST'}</span><span className="btn-secondary mono text-xs">View Details</span></div>
  </Link>;
}

function parseList(value?: string) {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return value.split('\n').map((item) => item.trim()).filter(Boolean);
  }
}

function LearningCard({ post }: { post: Post }) {
  const keyPoints = useMemo(() => parseList(post.keyPoints), [post.keyPoints]);
  const directions = useMemo(() => parseList(post.learningDirections), [post.learningDirections]);
  const [result, setResult] = useState<LearningDirectionResult | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [finding, setFinding] = useState(false);
  const [findMessage, setFindMessage] = useState('');

  useEffect(() => {
    const savedChecks = localStorage.getItem(`learning-check-v2-${post.id}`);
    const savedResult = localStorage.getItem(`learning-recommendations-${post.id}`);
    const legacyChecks = localStorage.getItem(`learning-check-${post.id}`);
    const timer = window.setTimeout(() => {
      try {
        const parsedChecks = savedChecks ? JSON.parse(savedChecks) : {};
        if (!savedChecks && legacyChecks) {
          const legacy = JSON.parse(legacyChecks) as boolean[];
          directions.forEach((direction, index) => {
            if (legacy[index]) parsedChecks[`draft:${direction}`] = true;
          });
        }
        setChecked(parsedChecks);
      } catch {
        setChecked({});
      }
      try {
        setResult(savedResult ? JSON.parse(savedResult) : null);
      } catch {
        setResult(null);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [post.id, directions]);

  function toggle(id: string) {
    const next = { ...checked, [id]: !checked[id] };
    setChecked(next);
    localStorage.setItem(`learning-check-v2-${post.id}`, JSON.stringify(next));
  }

  async function findGroundedDirections() {
    if (finding) return;
    setFinding(true);
    setFindMessage('내부 자료를 먼저 검색하고 있습니다...');
    try {
      const response = await authFetch(`/api/rag/learning-directions/${post.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          checkedDirectionIds: Object.entries(checked).filter(([, value]) => value).map(([id]) => id),
          includeWeb: true,
          maxRecommendations: 4,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as LearningDirectionResult;
      const incomingIds = new Set(data.recommendations.map((item) => item.id));
      const previousRecommendations: LearningRecommendation[] = result?.recommendations || directions.map((direction) => ({
        id: `draft:${direction}`,
        topic: direction,
        reason: '게시물 작성 시 생성된 기본 학습 방향',
        evidenceStatus: 'IDEA',
        citationNumbers: [],
      }));
      const preserved = previousRecommendations.filter(
        (item) => checked[item.id] && !incomingIds.has(item.id),
      );
      const combinedSources = [...data.sources];
      const preservedWithRemappedSources = preserved.map((item) => {
        const citationNumbers = item.citationNumbers.flatMap((oldNumber) => {
          const oldSource = (result?.sources || []).find((source) => source.citationNumber === oldNumber);
          if (!oldSource) return [];
          const existing = combinedSources.find((source) => source.url === oldSource.url);
          if (existing) return [existing.citationNumber];
          const citationNumber = combinedSources.reduce((max, source) => Math.max(max, source.citationNumber), 0) + 1;
          combinedSources.push({ ...oldSource, citationNumber });
          return [citationNumber];
        });
        return { ...item, citationNumbers };
      });
      const merged: LearningDirectionResult = {
        ...data,
        recommendations: [...data.recommendations, ...preservedWithRemappedSources],
        sources: combinedSources,
      };
      setResult(merged);
      localStorage.setItem(`learning-recommendations-${post.id}`, JSON.stringify(merged));
      setFindMessage(data.webSearchUsed
        ? '내부 자료가 부족한 항목만 웹 원출처로 보강했습니다.'
        : '내부 지식창고에서 우선 연결했습니다.');
    } catch {
      setFindMessage('학습 방향을 찾지 못했습니다. 로컬 AI와 검색 서비스 상태를 확인해주세요.');
    } finally {
      setFinding(false);
    }
  }

  const displayed: LearningRecommendation[] = result?.recommendations || directions.map((direction) => ({
    id: `draft:${direction}`,
    topic: direction,
    reason: '게시물 작성 시 생성된 기본 학습 방향',
    evidenceStatus: 'IDEA' as const,
    citationNumbers: [],
  }));

  return <article className="panel p-6">
    <div className="flex flex-wrap items-center gap-2"><span className={`border px-2 py-1 mono text-[10px] ${tagColors[post.categorySection || ''] || 'bg-slate-100 text-slate-700'}`}>{post.categoryName || '미분류'}</span><span className="mono text-[10px] text-[#667080]">{new Date(post.createdAt).toLocaleDateString('ko-KR')}</span></div>
    <h2 className="mt-3 text-xl font-bold text-[#002045]">{post.title}</h2>
    <section className="mt-5"><h3 className="text-sm font-bold text-[#002045]">요약</h3><p className="mt-2 text-sm leading-6 text-[#43474e]">{post.summary || '요약이 생성되지 않았습니다.'}</p></section>
    <section className="mt-5"><h3 className="text-sm font-bold text-[#002045]">핵심 내용</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-[#43474e]">{keyPoints.length ? keyPoints.map((point, index) => <li key={index}>{point}</li>) : <li>기존 게시물은 다시 저장하면 핵심 내용이 생성됩니다.</li>}</ul></section>
    <section className="mt-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-bold text-[#002045]">학습 방향 체크</h3><button type="button" onClick={findGroundedDirections} disabled={finding} className="btn-secondary text-xs disabled:opacity-50">{finding ? '검색 중...' : '근거 기반 학습 방향 찾기'}</button></div>
      {findMessage && <p className="mt-2 text-xs text-[#667080]">{findMessage}</p>}
      <div className="mt-3 space-y-3">{displayed.length ? displayed.map((item) => {
        const itemSources = (result?.sources || []).filter((source) => item.citationNumbers.includes(source.citationNumber));
        const badge = item.evidenceStatus === 'INTERNAL' ? '내부 자료' : item.evidenceStatus === 'WEB' ? '웹 원출처' : '추천 아이디어';
        return <div key={item.id} className="rounded border border-[#e0e3e5] bg-[#f8fafc] p-3"><label className="flex cursor-pointer items-start gap-3 text-sm leading-6 text-[#43474e]"><input type="checkbox" checked={Boolean(checked[item.id])} onChange={() => toggle(item.id)} className="mt-1 h-4 w-4"/><span className={checked[item.id] ? 'text-[#88909c] line-through' : ''}><b className="text-[#002045]">{item.topic}</b><span className="ml-2 rounded border px-1.5 py-0.5 mono text-[9px] text-[#455f88]">{badge}</span><span className="mt-1 block text-xs text-[#667080]">{item.reason}</span></span></label>{itemSources.length > 0 && <div className="mt-2 flex flex-wrap gap-2 pl-7">{itemSources.map((source) => <Link key={`${source.sourceType}-${source.citationNumber}`} href={source.url} target="_blank" rel="noopener noreferrer" title={source.snippet} className="rounded border border-[#8bdbe7] bg-[#eaf8fa] px-2 py-1 mono text-[10px] font-bold text-[#007d91] hover:border-[#002045]">근거 {source.citationNumber} · {source.title}<span className="ml-1 font-normal">({source.publisher}{source.checkedAt ? ` · ${new Date(source.checkedAt).toLocaleDateString('ko-KR')} 확인` : ''})</span></Link>)}</div>}</div>;
      }) : <p className="text-sm text-[#667080]">아직 추천할 학습 방향이 없습니다.</p>}</div>
      {result && <p className="mt-3 mono text-[10px] text-[#667080]">{result.retrievalMode || 'hybrid_rerank'} · {result.responseTimeMs ? `${(result.responseTimeMs / 1000).toFixed(1)}초` : '측정 없음'}</p>}
    </section>
    <Link href={`/posts/${post.id}`} className="mt-5 inline-block text-sm font-bold text-blue-700 hover:underline">원문 학습 게시글 보기 →</Link>
  </article>;
}

function LearningCards({ posts }: { posts: Post[] }) {
  return <div className="grid gap-5">{posts.map((post) => <LearningCard key={post.id} post={post}/>)}</div>;
}

export default function Home() {
  const [categories, setCategories] = useState<Category[]>(FALLBACK_CATEGORIES);
  const [posts, setPosts] = useState<Post[]>([]);
  const [section, setSection] = useState('ALL');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCategories().then(setCategories).catch(() => setCategories(FALLBACK_CATEGORIES));
    fetch(`${API_URL}/api/posts`).then((response) => response.ok ? response.json() : Promise.reject()).then(setPosts).catch(() => setPosts([])).finally(() => setLoading(false));
  }, []);

  const tabs = useMemo(() => [
    { section: 'ALL', name: '전체 (All)' },
    { section: 'LEARNING_LOG', name: '오늘의 학습 내용' },
    ...categories.filter((category) => category.section !== 'PROJECT_LOG').map((category) => ({ section: category.section, name: category.name })),
  ], [categories]);

  async function changeSection(nextSection: string) {
    setSection(nextSection);
    setLoading(true);
    const query = nextSection === 'ALL' || nextSection === 'LEARNING_LOG' ? '' : `?section=${encodeURIComponent(nextSection)}`;
    try {
      const response = await fetch(`${API_URL}/api/posts${query}`);
      if (!response.ok) throw new Error();
      setPosts(await response.json());
    } catch {
      setPosts([]);
    } finally {
      setLoading(false);
    }
  }

  return <div className="portal-page"><Header/><main className="portal-main space-y-8"><AiKnowledgeChat/>
    <nav className="hide-scrollbar flex gap-7 overflow-x-auto border-b border-[#c4c6cf]">{tabs.map((tab) => <button key={tab.section} onClick={() => changeSection(tab.section)} className={`whitespace-nowrap px-1 pb-3 mono text-[13px] ${section === tab.section ? 'border-b-2 border-[#002045] font-bold text-[#002045]' : 'text-[#545f72] hover:text-[#191c1e]'}`}>{tab.name}</button>)}</nav>
    {loading ? <div className="panel py-20 text-center mono text-sm text-[#545f72]">LOADING KNOWLEDGE FEED...</div> : posts.length === 0 ? <div className="panel py-20 text-center"><p className="text-[#545f72]">등록된 학습 지식이 없습니다.</p><Link href="/write" className="btn-primary mt-5 inline-block">첫 게시물 올리기</Link></div> : section === 'LEARNING_LOG' ? <LearningCards posts={posts}/> : <div className="grid gap-4 lg:grid-cols-2">{posts.map((post) => <PostCard key={post.id} post={post}/>)}</div>}
  </main><Footer/></div>;
}
