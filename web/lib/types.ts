export type Severity = "low" | "medium" | "high";
export type DecisionAction = "accept" | "reject" | "edit";

export interface SamplePrd {
  id: string;
  label: string;
  description: string;
  synthetic: boolean;
  content: string;
}

export interface FindingDecision {
  action: DecisionAction;
  edited_title?: string;
  edited_recommendation?: string;
}

export interface Finding {
  id: string;
  worker: string;
  category: string;
  severity: Severity;
  title: string;
  evidence: string;
  line: number;
  recommendation: string;
  confidence: number;
  decision: FindingDecision | null;
}

export interface WorkerRun {
  status: "completed" | "failed";
  output: Finding[];
  confidence: number;
  tokens_used: number;
}

export interface ReviewSnapshot {
  review_id: string;
  title: string;
  content: string;
  status: "completed";
  mode: "deterministic-demo";
  created_at: string;
  findings: Finding[];
  worker_runs: Record<string, WorkerRun>;
  advisor: { gaps: string[] };
}

export interface DecisionInput {
  finding_id: string;
  action: DecisionAction;
  edited_title?: string;
  edited_recommendation?: string;
}
