'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { api, ApiError } from '@/lib/care-api';
import Link from 'next/link';
import {usePathname} from 'next/navigation';

export interface CareIdentity { username: string; can_manage_reports: boolean;emergency_contact_complete?:boolean }
const AccountContext = createContext<CareIdentity | null>(null);
export const useCareAccount = () => useContext(AccountContext)?.username || '';
export const useCareIdentity = () => useContext(AccountContext);

export default function CareAccount({ children, requireManager = false }: { children: React.ReactNode; requireManager?: boolean }) {
  const [profile, setProfile] = useState<CareIdentity | null>(null);
  const [error, setError] = useState('');
  const pathname=usePathname();

  useEffect(() => {
    let active = true;
    const token = localStorage.getItem('access_token');
    function leave() {
      active = false;
      setProfile(null);
      sessionStorage.removeItem('care-report-scope');
      window.location.replace('/login');
    }
    function checkAccount() {
      if (localStorage.getItem('access_token') !== token) leave();
    }
    function storageChanged(event: StorageEvent) {
      if (event.key === 'access_token' || event.key === null) checkAccount();
    }
    window.addEventListener('storage', storageChanged);
    window.addEventListener('pageshow', checkAccount);
    window.addEventListener('focus', checkAccount);
    window.addEventListener('care-auth-required', leave);
    if (!token) {
      leave();
    } else {
      api<CareIdentity>('auth/me').then(profile => {
        if (active && localStorage.getItem('access_token') === token) setProfile(profile);
      }).catch(cause => {
        if (!active) return;
        if (cause instanceof ApiError && cause.status === 401) leave();
        else setError(cause instanceof Error ? cause.message : '暂时无法读取账号，请刷新重试。');
      });
    }
    return () => {
      active = false;
      window.removeEventListener('storage', storageChanged);
      window.removeEventListener('pageshow', checkAccount);
      window.removeEventListener('focus', checkAccount);
      window.removeEventListener('care-auth-required', leave);
    };
  }, []);

  useEffect(() => {
    if (profile?.can_manage_reports && !requireManager) window.location.replace('/care-admin');
  }, [profile, requireManager]);

  if (!profile) return <main className="care-main care-auth-loading">
    {error ? <div className="care-error" role="alert">{error}<p><button className="care-btn secondary" onClick={() => window.location.reload()}>重新加载</button></p></div> : <p role="status">正在读取账号…</p>}
  </main>;
  if (profile.can_manage_reports && !requireManager) return <main className="care-main care-auth-loading"><p role="status">正在进入报告管理…</p></main>;
  if (requireManager && !profile.can_manage_reports) return <main className="care-main care-auth-loading"><h1 className="care-title">此账号没有报告管理权限</h1><p>请使用机构授权的管理账号登录。</p><div className="care-actions"><Link className="care-btn" href="/robot-care">返回我的对话</Link><button className="care-btn secondary" onClick={() => { localStorage.removeItem('access_token'); window.location.replace('/login'); }}>切换账号</button></div></main>;
  if(!requireManager&&pathname.startsWith('/robot-care/voice')&&profile.emergency_contact_complete!==true)return <main className="care-main"><h1 className="care-title">请先补全紧急联系人</h1><p>开始新的语音对话前，需要登记一位已同意被联系的紧急联系人。</p><Link className="care-btn" href="/robot-care/profile">补全个人资料</Link></main>;
  return <AccountContext.Provider value={profile}>{children}</AccountContext.Provider>;
}
