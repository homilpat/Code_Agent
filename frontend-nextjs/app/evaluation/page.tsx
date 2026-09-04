'use client';

import { useEffect, useState } from 'react';
import Header from '@/components/layout/Header';
import Footer from '@/components/layout/Footer';
import { useRouter } from 'next/navigation';
import { authFetch, getUser } from '@/lib/auth-client';

type Summary = Record<string, number>;
type Profile = { summary: Summary };
type RouteCounts = Record<string, number>;
type StructureSummary = { summary: Summary; selected_routes: RouteCounts };
type RoutingSummary = Summary & { selected: RouteCounts };
type Report = {
  status: string;
  message?: string;
  created_at?: string;
  dataset_cases?: number;
  retrieval?: { profiles: Record<string, Profile> };
  generation?: { profiles: Record<string, Profile> };
  regressions?: { profile: string; id: string; query: string }[];
  deltas?: Record<string, Record<string, number>>;
  analysis?: {
    auto_routing?: RoutingSummary;
    by_expected_structure?: Record<string, Record<string, StructureSummary>>;
  };
};

const percent = (value?: number) => `${((value || 0) * 100).toFixed(1)}%`;

export default function EvaluationPage() {
  const router = useRouter();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    const user = getUser();
    if (user?.role !== 'ROLE_ADMIN') {
      router.replace(user ? '/' : '/auth');
      return;
    }

    authFetch('/api/rag/evaluation/latest')
      .then((response) => {
        if (!response.ok) throw new Error();
        return response.json();
      })
      .then((data) => {
        setReport(data);
        setAuthorized(true);
      })
      .catch(() => {
        setError('평가 결과를 불러오지 못했습니다.');
        setAuthorized(true);
      });
  }, [router]);

  if (!authorized) return null;

  return <div className="portal-page"><Header/><main className="portal-main space-y-7">
    <div><span className="mono text-[11px] text-[#06b6d4]">RAG QUALITY LAB</span><h1 className="mt-2 text-3xl font-bold text-[#002045]">Evaluation Dashboard</h1><p className="mt-2 text-sm text-[#545f72]">Golden set 기반 검색·생성 A/B 결과와 실패 회귀 사례를 확인합니다.</p></div>
    {error && <section className="panel p-5 text-sm text-red-700">{error}</section>}
    {!report && !error && <section className="panel p-5 text-sm">평가 결과를 불러오는 중입니다.</section>}
    {report?.status !== 'complete' && <section className="panel p-5 text-sm">{report?.message || '아직 실행된 평가가 없습니다.'}</section>}
    {report?.status === 'complete' && <>
      <section className="grid gap-4 md:grid-cols-3"><div className="panel p-5"><span className="mono text-[10px] text-[#667080]">GOLDEN CASES</span><b className="mt-2 block text-3xl text-[#002045]">{report.dataset_cases}</b></div><div className="panel p-5"><span className="mono text-[10px] text-[#667080]">LAST RUN</span><b className="mt-2 block text-sm text-[#002045]">{report.created_at ? new Date(report.created_at).toLocaleString('ko-KR') : '-'}</b></div><div className="panel p-5"><span className="mono text-[10px] text-[#667080]">REGRESSIONS</span><b className="mt-2 block text-3xl text-[#002045]">{report.regressions?.length || 0}</b></div></section>
      <section className="panel overflow-x-auto p-5"><h2 className="text-lg font-bold text-[#002045]">Retrieval comparison</h2><table className="mt-4 w-full min-w-[680px] text-left text-xs"><thead className="border-b"><tr><th className="py-2">전략</th><th>Hit@K</th><th>Recall@K</th><th>MRR</th><th>평균 지연</th></tr></thead><tbody>{Object.entries(report.retrieval?.profiles || {}).map(([name, profile]) => <tr key={name} className="border-b border-[#edf0f3]"><th className="py-3 mono">{name}</th><td>{percent(profile.summary.hit_at_k)}</td><td>{percent(profile.summary.recall_at_k)}</td><td>{profile.summary.mrr?.toFixed(3)}</td><td>{profile.summary.latency_ms?.toFixed(1)}ms</td></tr>)}</tbody></table></section>
      <section className="panel overflow-x-auto p-5"><h2 className="text-lg font-bold text-[#002045]">Generation A/B</h2><table className="mt-4 w-full min-w-[760px] text-left text-xs"><thead className="border-b"><tr><th className="py-2">프로필</th><th>통과율</th><th>정확성</th><th>근거 블록</th><th>인용 유효성</th><th>평균 지연</th></tr></thead><tbody>{Object.entries(report.generation?.profiles || {}).map(([name, profile]) => <tr key={name} className="border-b border-[#edf0f3]"><th className="py-3 mono">{name}</th><td>{percent(profile.summary.pass_rate)}</td><td>{percent(profile.summary.accuracy)}</td><td>{percent(profile.summary.grounded_block_ratio)}</td><td>{percent(profile.summary.citation_validity)}</td><td>{(profile.summary.latency_ms / 1000).toFixed(1)}초</td></tr>)}</tbody></table></section>
      {report.analysis?.auto_routing && <section className="panel p-5"><h2 className="text-lg font-bold text-[#002045]">Auto routing accuracy</h2><div className="mt-4 grid gap-4 md:grid-cols-3"><div><span className="mono text-[10px] text-[#667080]">ROUTE ACCURACY</span><b className="mt-1 block text-2xl text-[#002045]">{percent(report.analysis.auto_routing.accuracy)}</b></div><div><span className="mono text-[10px] text-[#667080]">INTENT ACCURACY</span><b className="mt-1 block text-2xl text-[#002045]">{percent(report.analysis.auto_routing.intent_accuracy)}</b></div><div><span className="mono text-[10px] text-[#667080]">STRUCTURE ACCURACY</span><b className="mt-1 block text-2xl text-[#002045]">{percent(report.analysis.auto_routing.structure_accuracy)}</b></div></div><p className="mt-4 text-xs text-[#545f72]">잘못된 직접 경로 {report.analysis.auto_routing.wrong_direct || 0}건 · 불필요한 계층형 {report.analysis.auto_routing.unnecessary_hierarchical || 0}건 · 우회 실패 {(report.analysis.auto_routing.missed_bypass || 0) + (report.analysis.auto_routing.unexpected_bypass || 0)}건</p></section>}
      <section className="panel overflow-x-auto p-5"><h2 className="text-lg font-bold text-[#002045]">Quality by question structure</h2><table className="mt-4 w-full min-w-[900px] text-left text-xs"><thead className="border-b"><tr><th className="py-2">프로필</th><th>기대 구조</th><th>문항</th><th>통과율</th><th>정확성</th><th>근거 블록</th><th>인용</th><th>경로 분포</th></tr></thead><tbody>{Object.entries(report.analysis?.by_expected_structure || {}).flatMap(([profile, structures]) => Object.entries(structures).map(([structure, value]) => <tr key={`${profile}-${structure}`} className="border-b border-[#edf0f3]"><th className="py-3 mono">{profile}</th><td className="mono">{structure}</td><td>{value.summary.cases}</td><td>{percent(value.summary.pass_rate)}</td><td>{percent(value.summary.accuracy)}</td><td>{percent(value.summary.grounded_block_ratio)}</td><td>{percent(value.summary.citation_validity)}</td><td className="mono">{Object.entries(value.selected_routes).filter(([, count]) => count > 0).map(([route, count]) => `${route}:${count}`).join(' · ')}</td></tr>))}</tbody></table></section>
      <section className="panel p-5"><h2 className="text-lg font-bold text-[#002045]">자동 등록된 회귀 사례</h2>{report.regressions?.length ? <ul className="mt-4 space-y-3 text-sm">{report.regressions.slice(0, 20).map((item) => <li key={`${item.profile}-${item.id}`} className="border-l-2 border-amber-400 pl-3"><b className="mono text-xs">{item.profile} · {item.id}</b><p className="mt-1 text-[#545f72]">{item.query}</p></li>)}</ul> : <p className="mt-3 text-sm text-emerald-700">등록된 실패 사례가 없습니다.</p>}</section>
    </>}
  </main><Footer/></div>;
}
