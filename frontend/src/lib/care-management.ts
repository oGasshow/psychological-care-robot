export interface ManagedUser {
  user_id:number;username:string;is_active:boolean;is_test:boolean;report_count:number;
  latest_session_id:number|null;latest_at:string|null;
}
