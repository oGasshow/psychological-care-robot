import ManagementUser from '@/components/care-management-user';
export default async function Page({params,searchParams}:{params:Promise<{userId:string}>;searchParams:Promise<{test?:string}>}){
  const {userId}=await params;
  const query=await searchParams;
  return <ManagementUser key={`${userId}:${query.test}`} userId={Number(userId)} isTest={query.test==='1'}/>;
}
