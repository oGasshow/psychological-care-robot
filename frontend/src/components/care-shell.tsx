'use client';
import DeploymentModeNotice from '@/components/deployment-mode';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api, ApiError, natureNotice } from '@/lib/care-api';

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="care-error" role="alert">{error instanceof Error ? error.message : '请求失败，请重试。'}{error instanceof ApiError && error.status === 401 && <Link href="/login">重新登录</Link>}</div>;
}

export default function CareShell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  const [username, setUsername] = useState('');
  const [error, setError] = useState<unknown>(null);
  const path = usePathname();
  const router = useRouter();
  useEffect(() => {
    let active = true;
    api<{username: string}>('auth/me').then(profile => {
      if (active) setUsername(profile.username);
    }).catch(e => { if (active) setError(e); });
    return () => { active = false; };
  }, []);
  const nav = [['/robot-care/voice', '语音陪伴'], ['/robot-care', '对话记录'], ['/robot-care/assessments', '量表结果'], ['/robot-care/trends', '分类与分数趋势'], ['/robot-care/report', '报告摘要']];
  return <>
    <header className="care-top care-no-print"><Link href="/robot-care" className="care-brand">陪伴记录<small>ROBOT CARE / 辅助陪伴工作台</small></Link><div className="care-account">{username&&<strong data-testid="account-username">{username}</strong>}<button className="care-btn secondary" style={{marginLeft:18}} onClick={() => { localStorage.removeItem('access_token'); sessionStorage.removeItem('care-report-scope'); router.push('/login'); }}>退出登录</button></div></header>
    <nav className="care-nav care-no-print" aria-label="陪伴记录导航">{nav.map(([href,text]) => <Link key={href} href={href} className={path === href || href !== '/robot-care' && path.startsWith(href) ? 'active' : ''}>{text}</Link>)}</nav>
    <main className="care-main"><DeploymentModeNotice/><div className="care-no-print"><div className="care-eyebrow">辅助陪伴 · 来源可追溯</div><h1 className="care-title">{title}</h1>{subtitle && <p className="care-subtitle">{subtitle}</p>}<ErrorBox error={error}/></div>{children}<footer className="care-footer care-no-print">{natureNotice}</footer></main>
  </>;
}
