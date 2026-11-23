'use client';
import {useEffect,useState} from 'react';
import {api} from '@/lib/care-api';
import CareShell,{ErrorBox} from '@/components/care-shell';
const empty={full_name:'',gender:'',age:'',emergency_contact_name:'',emergency_contact_phone:'',emergency_contact_authorized:false};
export default function ProfilePage(){
  const [form,setForm]=useState(empty),[busy,setBusy]=useState(true),[error,setError]=useState<unknown>(null);
  useEffect(()=>{const r=new AbortController();api<{report_profile:Record<string,string|number|null>}>('auth/me',{signal:r.signal}).then(v=>{
    if(r.signal.aborted)return;const p=v.report_profile;setForm({...empty,full_name:String(p.full_name||''),gender:String(p.gender||''),age:p.age==null?'':String(p.age),emergency_contact_name:String(p.emergency_contact_name||''),emergency_contact_phone:String(p.emergency_contact_phone||'')});
  }).catch(e=>{if(!r.signal.aborted)setError(e);}).finally(()=>{if(!r.signal.aborted)setBusy(false);});return()=>r.abort();},[]);
  async function save(e:React.FormEvent){e.preventDefault();setBusy(true);setError(null);
    try{await api('auth/profile',{method:'PUT',body:JSON.stringify({...form,full_name:form.full_name.trim()||null,gender:form.gender||null,age:form.age===''?null:Number(form.age)})});window.location.replace('/robot-care/voice');}
    catch(e){setError(e);setBusy(false);}
  }
  return <CareShell title="个人资料与紧急联系人" subtitle="紧急联系人用于需要时由管理员人工联系。姓名、性别和年龄可选填。"><ErrorBox error={error}/><form className="care-card" onSubmit={save}>
    <label htmlFor="profile-name">姓名／称呼</label><input id="profile-name" value={form.full_name} maxLength={50} onChange={e=>setForm({...form,full_name:e.target.value})}/>
    <label htmlFor="profile-gender">性别</label><select id="profile-gender" value={form.gender} onChange={e=>setForm({...form,gender:e.target.value})}><option value="">未填写</option><option value="male">男</option><option value="female">女</option><option value="other">其他</option><option value="undisclosed">不便透露</option></select>
    <label htmlFor="profile-age">年龄</label><input id="profile-age" type="number" min={1} max={120} step={1} value={form.age} onChange={e=>setForm({...form,age:e.target.value})}/>
    <label htmlFor="profile-contact-name">紧急联系人姓名（必填）</label><input id="profile-contact-name" required maxLength={50} value={form.emergency_contact_name} onChange={e=>setForm({...form,emergency_contact_name:e.target.value})}/>
    <label htmlFor="profile-contact-phone">紧急联系人电话（必填）</label><input id="profile-contact-phone" type="tel" required maxLength={32} value={form.emergency_contact_phone} onChange={e=>setForm({...form,emergency_contact_phone:e.target.value})}/>
    <label><input type="checkbox" required checked={form.emergency_contact_authorized} onChange={e=>setForm({...form,emergency_contact_authorized:e.target.checked})}/> 已获得联系人同意，将其姓名和电话用于紧急联系。</label>
    <button className="care-btn" disabled={busy} type="submit">保存并继续</button></form></CareShell>;
}
