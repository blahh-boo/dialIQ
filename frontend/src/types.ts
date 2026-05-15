export type Tier = 'HOT' | 'WARM' | 'COLD';

export type AnsweredBy = 'HUMAN' | 'VOICEMAIL' | 'IVR' | 'NO_ANSWER' | 'BUSY';

export interface CallFacts {
  pickup: boolean;
  rings_to_answer: number | null;
  put_on_hold: boolean;
  hold_time_seconds: number | null;
  transfer_count: number;
  call_abandoned_by_restaurant: boolean;
  interruption_count: number;
  repeated_information_count: number;
  upsell_attempted: boolean;
  customer_effort_score: number;
  key_failure_quote: string | null;
}

export interface Deduction {
  reason: string;
  points: number;
}

export interface ScoreResult {
  pickup: boolean;
  numeric_score: number;
  tier: Tier;
  deductions: Deduction[];
  rubric_version: string;
}

export interface LeadCallInfo {
  attempt_id: number;
  started_at: string | null;
  duration_seconds: number | null;
  vapi_call_id: string | null;
}

export interface SdrState {
  dialed_today: boolean;
  contacted_today: boolean;
  snoozed_until: string | null;
}

export interface Lead {
  id: number;
  restaurant_name: string;
  phone_e164: string;
  phone_display: string;
  address: string | null;
  city: string | null;
  state: string | null;
  cuisine_type: string | null;
  website: string | null;
  google_reviews_count: number | null;
  answered_by: AnsweredBy;
  key_failure_quote: string | null;
  one_liner: string | null;
  call: LeadCallInfo;
  facts: CallFacts;
  score: ScoreResult;
  sdr_state: SdrState;
}

export interface TranscriptTurn {
  role: 'shopper' | 'restaurant' | 'system';
  text: string;
  t: number;
}

export interface LeadDetail {
  lead: Lead;
  transcript: TranscriptTurn[];
  recording_url: string | null;
}

export interface CampaignStats {
  campaign_name: string;
  total_leads: number;
  mystery_shopped: number;
  avg_score: number;
  hot_count: number;
  no_pickup_count: number;
  touched_today: number;
}

export interface Me {
  id: number;
  name: string;
  initials: string;
  email: string;
}
