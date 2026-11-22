'use client';
import DeploymentModeNotice from '@/components/deployment-mode';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useCareAccount } from '@/components/care-account';
import { ApiError, natureNotice } from '@/lib/care-api';

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="care-error" role="alert">{error instanceof Error ? error.message : '请求失败，请重试。'}{error instanceof ApiError && error.status === 401 && <Link href="/login">重新登录</Link>}</div>;
}

export default function CareShell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  const username = useCareAccount();
  const path = usePathname();
  const nav = [['/robot-care', '我的对话'], ['/robot-care/voice', '语音陪伴'], ['/robot-care/assessments', '我的量表'], ['/robot-care/trends', '分类与分数趋势'], ['/robot-care/report', '报告摘要']];
  return <>
    <header className="care-top care-no-print"><Link href="/robot-care" className="care-brand">心理陪伴</Link><div className="care-account"><strong data-testid="account-username">{username}</strong><button className="care-btn secondary" onClick={() => { localStorage.removeItem('access_token'); sessionStorage.removeItem('care-report-scope'); window.location.replace('/login'); }}>退出登录</button></div></header>
    <nav className="care-nav care-no-print" aria-label="陪伴记录导航">{nav.map(([href,text]) => <Link key={href} href={href} className={path === href || href === '/robot-care' && path.startsWith('/robot-care/sessions/') || href !== '/robot-care' && path.startsWith(href) ? 'active' : ''}>{text}</Link>)}</nav>
    <main className="care-main"><DeploymentModeNotice/><div className="care-no-print"><h1 className="care-title">{title}</h1>{subtitle && <p className="care-subtitle">{subtitle}</p>}</div>{children}<footer className="care-footer care-no-print">{natureNotice}</footer></main>
  </>;
}
