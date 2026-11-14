/** JSON contracts used by care views; optional fields mirror partial/legacy data. */
export interface Page<T> { items: T[]; next_cursor: string | null }
export interface SessionRecord {
  recording_session_id: number; external_session_id: string; device_id: string;
  is_test: boolean; state: string; is_complete: boolean; started_at: string;
  ended_at: string | null; received_record_count: number; last_sequence_no: number | null;
}
export interface MessageRecord {
  record_id: number; sequence_no: number; role: string; text_status: string;
  playback_status: string; is_test: boolean; occurred_at: string; turn_id: string | null; content: string;
}
export interface EffectiveMessage {
  effective_content: string; original_content: string; input_revision: number; corrected_at: string | null;
}
export interface DangerSource {
  record_id: number; recording_session_id: number; input_revision: number;
  occurred_at: string; is_test: boolean; expressions: string[];
}
export interface DangerNoticeData { action?: string; sources?: DangerSource[] }
export interface AnalysisResult {
  target_record_id?: number; input_revision?: number; analyzed_at?: string;
  classification_status?: string; emotion_label?: string | null; is_current?: boolean;
  reason_code?: string; engine_kind?: string; engine_version?: string; config_version?: string;
  matched_rule_ids?: string[]; safety_signal?: string; support_policy_id?: number;
}
export interface AnalysisEntry extends AnalysisResult {
  task_id: number; job_id?: number; status?: string; error_code?: string; result?: AnalysisResult;
}
export interface ExcludedRecord { record_id?: number; target_record_id?: number; reason_code?: string; exclusion_reason?: string }
export interface AnalysisPage extends Page<AnalysisEntry> { excluded_records?: ExcludedRecord[] }
export interface AnalysisReference extends AnalysisResult { record_id: number; analysis_state?: string }
export interface SessionSummary {
  state: string; is_complete: boolean; data_as_of: string; emotion_counts?: Record<string, number>;
  analysis_counts?: Record<string, number>; danger_notice?: DangerNoticeData; source_references?: AnalysisReference[];
}
export interface SupportPolicy {
  content?: string; text?: string; support_text?: string; response_text?: string;
  template_version: string; policy_kind: string; review_state: string; simulator_enabled?: boolean;
}
export interface DeliveryReceipt { delivery_status: string; consumer_kind: string }
export interface Assessment {
  source_record_id?: number | string; display_name?: string; scale_name?: string; is_test?: boolean;
  verification_status?: string; applicability_status?: string; total_score?: number | null;
  score_min?: number | null; score_max?: number | null; completed_at?: string | null;
  time_source?: string; completed_at_source?: string; source_kind?: string; scale_version?: string;
  scoring_version?: string; interpretation_version?: string; content_review_status?: string;
  review_reference?: string | Record<string, unknown> | null; reference_interpretation?: string;
  reference_advice?: string; suggestions?: string | string[]; reason_code?: string;
  verification_reason?: string; verification_reasons?: string[];
}
export interface TrendPoint extends Assessment {
  record_id?: number; target_record_id?: number; occurred_at?: string; emotion_label?: string; input_revision?: number;
}
export interface TrendGroup {
  points?: TrendPoint[]; is_test?: boolean; engine_kind?: string; engine_version?: string; config_version?: string;
  reason_code?: string; display_name?: string; scale_name?: string; scale_version?: string; source_kind?: string;
}
export interface TrendsData { emotion_groups?: TrendGroup[]; assessment_groups?: TrendGroup[] }
export interface CollectionScale {
  scale: string; display_name?: string; answered: number; required: number; total?: number | null;
  max_score?: number; direction?: string; score_kind?: string;
}
export interface CollectionObservation { display_name?: string; scale: string; item: number; status: string }
export interface CollectionResult {
  saved_answer_review?: {state:string;updated_at:string};
  demo_mode?: boolean; trigger_origin?: string;
  history_danger_unresolved?: boolean;
  recording_session_id: number; started_at: string; is_test: boolean; stage: string; detector_status: string;
  history_session_ids?: number[]; observations?: CollectionObservation[]; source_status: string; scales?: CollectionScale[];
}
export interface CollectionPlan { needs_collection: boolean; status: string; scales: CollectionScale[] }
export interface AssessmentsData {
  demo_mode?: boolean;
  after_call_review_mode?: string; after_call_reviews?: AfterCallReview[];
  collection_plan?: CollectionPlan; conversation_collections?: CollectionResult[];
  provider: string; status?: string; provider_status?: string; source_kind?: string; items?: Assessment[];
}
export interface AfterCallReview {
  recording_session_id: number; state: string; attempt: number; updated_at: string; error_code?: string | null;
  decision?: string | null; target_scales: string[]; message: string;
}
export interface TimeScope { time_from: string; time_to: string; session_ids?: undefined }
export type ReportScope = TimeScope | { session_ids: number[]; time_from?: string; time_to?: string };
export interface ReportEvidence {
  id: string; occurred_at: string; record_id: number; recording_session_id: number;
  input_revision: number; is_test: boolean; text: string; truncated: boolean;
}
export interface ReportFact {
  id: string; kind: string; is_test?: boolean; active_days?: number; classified_count?: number; user_text_count?: number;
}
export interface ReportCoverage {
  is_test: boolean; active_days: number; window_days: number; classified_count: number;
  user_text_count: number; unclassified_count: number; latest_record_at: string;
}
export interface DailyCounts {
  day: string; positive: number; neutral: number; negative: number; classified_count: number; has_user_records: boolean;
}
export type Comparison = { eligible: false; reason_code: string } | {
  eligible: true; previous_counts: Record<string, number>; previous_count: number; negative_share_delta_pp: number;
};
export interface ReportGroup {
  daily?: DailyCounts[]; comparison: Comparison; is_test: boolean; counts: Record<string, number>;
  classified_count: number; engine_kind: string; engine_version: string; config_version: string;
}
export interface ReportFacts {
  data_nature?: string; evidence?: ReportEvidence[]; facts?: ReportFact[]; coverage?: ReportCoverage[];
  groups?: ReportGroup[]; topics?: { is_test: boolean; title: string; evidence_ids: string[] }[];
  evidence_selection?: { sampled?: boolean; danger_excluded_count?: number }; comparison_scope?: ReportScope;
}
export interface NarrativeSection { text: string; evidence_ids?: string[] }
export interface NarrativeContent {
  overview?: NarrativeSection; changes?: NarrativeSection[]; topics?: NarrativeSection[];
  conversation_suggestions?: NarrativeSection[]; limitations?: NarrativeSection[];
}
export interface ReportNarrative { mode: string; reason_code?: string; content?: NarrativeContent; prompt_version?: string; model?: string }
export interface ReportData {
  scope: ReportScope; generated_at: string; anonymous_id: string; data_as_of: string;
  schema_version: string; source_snapshot_hash: string; narrative: ReportNarrative;
  report_facts?: ReportFacts; danger_notice?: DangerNoticeData; conversation_assessments?: CollectionResult[];
  sessions?: { is_complete: boolean }[]; source_references?: Record<string, unknown>[];
}
export interface SegaStatus { message: string; probe_allowed: boolean; installed: boolean }
export interface SegaProbe { status: string; device?: string }
export interface VoiceConfig { enabled: boolean; conditional_collection_enabled: boolean; is_test: boolean; message: string; concern_review_mode?: string; demo_mode?: boolean }
export interface DeploymentMode { mode:'normal'|'demo'|'unavailable';name:string;demo_mode:boolean;description?:string }
export interface ScreeningStatus {
  type: 'screening.status'; stage: string; version: number; triggered: boolean; detector_status: string;
  review_status: string; error_code?: string;
  review_mode?: string;
  demo_mode?: boolean;trigger_origin?:string;
  demo_progress?: {answered:number;required:number;total:number|null;max_score:number}|null;
}
export interface RecordingReceipt {
  type: 'records.saved' | 'records.pending' | 'records.error'; recording_session_id?: number; pending?: number; message?: string;
}
export interface VoiceDiagnostics {
  active: boolean; message: string; user_turns?: number; checked_user_turns?: number; stage?: string;
  detector_status?: string; last_error_code?: string | null; sent_policy_version?: number | null; applied_policy_version?: number | null;
  transport?: { last_remote_event?: string; last_remote_event_age_seconds?: number; audio_frames?: number;
    session_ready_ms?: number; last_final_role?: string; last_final_age_seconds?: number; capture_gap_count?: number };
}
export interface AudioDelta { type: 'audio.delta'; message_id: string; audio: string; rate: number }
export type VoiceEvent = AudioDelta | ScreeningStatus | RecordingReceipt
  | { type: 'transcript.delta' | 'transcript.final'; message_id: string; role: string; text: string; interrupted?: boolean; occurred_at?: string }
  | { type: 'audio.done'; message_id: string }
  | { type: 'screening.result_failed' | 'error'; message: string }
  | { type: 'status'; state: string; message: string }
  | { type: 'dialogue.finished' | 'session.ready' | 'playback.clear' | 'screening.policy_applied' | 'screening.detector_checked' | 'playback.status' };
