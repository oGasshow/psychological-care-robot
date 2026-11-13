/** Diary JSON fields shared by the editor and the saved-detail view. */
export interface GuidedResponses {
  question: string;
  answer: string;
}

export interface DiaryRecommendation {
  type: string;
  title: string;
  reason: string;
}

export interface DiaryFeedback {
  emotion_analysis?: {
    primary_emotion: string;
    emotion_intensity: number;
    emotion_valence: string;
  };
  life_quality?: string[];
  positive_highlights?: string[];
  recommendations?: DiaryRecommendation[];
  overall_score?: number;
}
