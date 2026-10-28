'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api, ApiError, insights, natureNotice } from '@/lib/care-api';

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="care-error" role="alert">{error instanceof Error ? error.message : '请求失败，请重试。'}{error instanceof ApiError && error.status === 401 && <Link href="/login">重新登录</Link>}</div>;
}

export default function CareShell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  const [anonymousId, setAnonymousId] = useState('加载中');
  const [error, setError] = useState<unknown>(null);
  const path = usePathname();
  const router = useRouter();
  useEffect(() => {
    let active = true;
    Promise.all([api('auth/me'), insights('profile')]).then(([, profile]) => {
      if (active) setAnonymousId(profile.anonymous_id || profile.anonymous_code || '未提供');
    }).catch(e => { if (active) { setError(e); setAnonymousId('未登录'); } });
    return () => { active = false; };
  }, []);
  const nav = [['/robot-care', '对话记录'], ['/robot-care/assessments', '量表结果'], ['/robot-care/trends', '分类与分数趋势'], ['/robot-care/report', '报告摘要']];
  return <>
    <header className="care-top care-no-print"><Link href="/robot-care" className="care-brand">心翼 · 陪伴记录<small>ROBOT CARE / 辅助陪伴工作台</small></Link><div className="care-anon">匿名展示编号<br/><strong data-testid="anonymous-id">{anonymousId}</strong><button className="care-btn secondary" style={{marginLeft:18}} onClick={() => { localStorage.removeItem('access_token'); sessionStorage.removeItem('care-report-scope'); router.push('/login'); }}>退出登录</button></div></header>
    <nav className="care-nav care-no-print" aria-label="陪伴记录导航">{nav.map(([href,text]) => <Link key={href} href={href} className={path === href || href !== '/robot-care' && path.startsWith(href) ? 'active' : ''}>{text}</Link>)}</nav>
    <main className="care-main"><div className="care-no-print"><div className="care-eyebrow">辅助陪伴 · 来源可追溯</div><h1 className="care-title">{title}</h1>{subtitle && <p className="care-subtitle">{subtitle}</p>}<ErrorBox error={error}/></div>{children}<footer className="care-footer care-no-print">{natureNotice}</footer></main>
  </>;
}
