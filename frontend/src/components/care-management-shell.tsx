'use client';
import Link from 'next/link';
import {useCareAccount} from './care-account';
import {natureNotice} from '@/lib/care-api';

export default function ManagementShell({title,subtitle,children}:{title:string;subtitle?:string;children:React.ReactNode}){
  const username=useCareAccount();
  return <>
    <header className="care-top care-no-print"><Link href="/care-admin" className="care-brand">心理陪伴 · 报告管理</Link><div className="care-account"><strong data-testid="account-username">{username}</strong><button className="care-btn secondary" onClick={()=>{localStorage.removeItem('access_token');sessionStorage.removeItem('care-report-scope');window.location.replace('/login');}}>退出登录</button></div></header>
    <nav className="care-nav care-no-print" aria-label="报告管理导航"><Link href="/care-admin" className="active">用户报告</Link></nav>
    <main className="care-main management-main"><div className="care-no-print"><h1 className="care-title">{title}</h1>{subtitle&&<p className="care-subtitle">{subtitle}</p>}</div>{children}<footer className="care-footer care-no-print">{natureNotice}</footer></main>
  </>;
}
