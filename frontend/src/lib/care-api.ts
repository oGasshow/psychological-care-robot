export type Data = Record<string, any>;

export class ApiError extends Error {
  constructor(public status: number, public code: string) {
    super(status === 401 ? '登录已失效，请重新登录。' : status === 403 ? '当前账号不可用。' : status === 404 ? '记录不存在或不属于当前用户。' : status === 410 ? '会话已删除，无法继续读取。' : status === 409 ? '记录版本已经变化，请刷新后重试。' : status === 422 ? '字段或范围无效，请检查输入。' : '服务暂不可用，请稍后重试。');
  }
}

export async function api(path: string, init: RequestInit = {}): Promise<Data> {
  const token = localStorage.getItem('access_token');
  if (!token) throw new ApiError(401, 'authentication_required');
  const response = await fetch(`/api/${path}`, {
    ...init, cache: 'no-store',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) localStorage.removeItem('access_token');
    throw new ApiError(response.status, data?.error?.code || 'request_failed');
  }
  return data;
}

export const insights = (path: string, init?: RequestInit) => api(`robot-insights/${path}`, init);
export const list = (value: unknown): Data[] => Array.isArray(value) ? value : [];
export const date = (value: unknown): string => {
  if (typeof value !== 'string' || !value) return '未提供';
  const d = new Date(value);
  return Number.isNaN(d.valueOf()) ? '时间未确认' : `${d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}（UTC+8）`;
};
export const label = (value: unknown): string => ({
  positive: '积极', neutral: '中性', negative: '消极', unable_to_determine: '无法判断',
  classified: '已分类', pending: '待分析', running: '分析中', retry_wait: '等待重试',
  succeeded: '已完成', failed: '分析失败', invalidated: '已过期', excluded: '不参与分析',
  open: '进行中', closed: '已关闭', completed: '文本完成', canceled: '文本取消',
  unknown: '播放情况未知', interrupted: '播放中断', played: '已播放', not_applicable: '不适用',
  not_started: '尚未播放', playing: '播放中', none_detected: '未检出规则信号（不代表无风险）',
  explicit_danger_expression: '检出明确危险表达', undetermined: '安全信号无法判断',
  verified_fixture: '演示契约已验证', verified_live: '来源已验证', unverified: '未确认',
  demo_only: '仅演示适用', fixture: '虚构演示数据', live: '既有量表只读来源', disabled: '量表来源未启用',
  insufficient_data: '独立有效记录不足', no_records: '暂无记录', query_failed: '查询失败',
  incomplete: '尚未完成', invalid: '记录无效', not_connected: '真实接收未连接',
  simulated_received: '本地模拟器已接收', simulated_rejected: '本地模拟器已拒绝',
}[String(value)] || String(value ?? '未提供'));

export const natureNotice = '本系统为辅助陪伴设备，非专业心理咨询师或医疗服务设备。文本分析和量表展示不构成确定性诊断，也不能替代专业评估。';
export const playbackLabel = (value:unknown):string => value==='completed' ? '播放完成' : label(value);
