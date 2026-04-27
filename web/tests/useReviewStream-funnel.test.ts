/**
 * useReviewStream funnel event 类型检查 · 2026-04-28 step 1b
 *
 * 跑:cd web && pnpm vitest run tests/useReviewStream-funnel.test.ts
 *
 * 范围:
 * 1. 7 个 funnel event interface (5 新增 + final_reviewer_done 升级 + evidence_verify_done 升级)
 *    在 ReviewStreamEvent union 里能被正确 narrow.
 * 2. 验 mock SSE payload 能被 JSON.parse 后赋给对应 interface (TypeScript 编译期 + runtime).
 * 3. 字段对齐 review/funnel_telemetry.py 各 compute_* 函数返回 schema.
 *
 * 不测 SSE 帧解析自身 (splitSseFrames / parseSseFrame 是 file-private);
 * 那部分由 e2e Playwright 测试覆盖.
 */

import { describe, it, expect } from "vitest";
import type {
  ReviewStreamEvent,
  FunnelStageWorkerRawEvent,
  FunnelStageAfterDedupEvent,
  FunnelStageAfterEvidenceVerifyEvent,
  FunnelStageAfterGoshawkEvent,
  FunnelSummaryEvent,
  FinalReviewerDoneEvent,
  EvidenceVerifyDoneEvent,
} from "@/lib/useReviewStream";

// ============================================================
// 后端真实 emit_and_log payload 的 mock fixture
// (字段对齐 review/funnel_telemetry.py 各 compute_*)
// ============================================================

const FIXTURE_WORKER_RAW = {
  event: "funnel_stage_worker_raw",
  progress: null,
  label: "N0 worker 原始产出",
  count: 28,
  by_dimension: { structure: 7, quality: 8, data_quality: 6, ai_coding: 7 },
  empty_retry_dimensions: [],
  dropped_unknown_rule_count: 0,
  dropped_unknown_rule_ids_by_dim: {},
} as const;

const FIXTURE_AFTER_DEDUP = {
  event: "funnel_stage_after_dedup",
  progress: null,
  label: "N1 去重后",
  count: 22,
  dropped_count: 6,
} as const;

const FIXTURE_AFTER_EVIDENCE_VERIFY = {
  event: "funnel_stage_after_evidence_verify",
  progress: null,
  label: "N2 evidence verify 后",
  count: 18,
  retracted_count: 3,
  downgraded_count: 1,
  retracted_by_reason: { no_wiki_match: 2, wiki_contradicts: 1 },
  downgraded_by_reason: { partial_match: 1 },
  wiki_mode: "rich" as const,
  authority_distribution: { canonical: 12, contextual: 6 },
} as const;

const FIXTURE_AFTER_GOSHAWK = {
  event: "funnel_stage_after_goshawk",
  progress: null,
  label: "N3 苍鹰终审后",
  count: 17,
  delta_breakdown: {
    removed: 1,
    merged_to_facet: 2,
    added: 0,
    false_positive_restored: 0,
    kept_intact: 14,
  },
  facet_links: [{ facet: "STR-001-A", primary: "STR-001" }],
} as const;

const FIXTURE_FUNNEL_SUMMARY = {
  event: "funnel_summary",
  progress: null,
  label: "漏斗汇总",
  stages: {
    N0_worker_raw: 28,
    N1_after_dedup: 22,
    N2_after_evidence_verify: 18,
    N3_after_goshawk: 17,
  },
  stage_retention: {
    dedup_retention: 0.786,
    evidence_verify_retention: 0.818,
    goshawk_retention: 0.944,
  },
  suspicious_flags: [],
} as const;

const FIXTURE_FINAL_REVIEWER_DONE = {
  event: "final_reviewer_done",
  progress: 95,
  label: "终审完成",
  false_positive: 1,
  additional: 2,
  verdict: "REVIEWED",
  confidence: 0.85,
  empty_retry_used: false,
  n_samples: 4,
  n_samples_succeeded: 4,
  retention_kind_dist: { unanimous: 12, majority: 4, minority: 1 },
  minority_kept: 1,
} as const;

const FIXTURE_EVIDENCE_VERIFY_DONE = {
  event: "evidence_verify_done",
  progress: null,
  label: "evidence verify 完成",
  retracted: 3,
  caveat: 2,
  wiki_mode: "rich" as const,
  authority_distribution: { canonical: 12, contextual: 6 },
} as const;

// ============================================================
// Tests
// ============================================================

describe("funnel event interface · payload 解析", () => {
  it("FunnelStageWorkerRawEvent · count + by_dimension 分布", () => {
    // SSE 实际收到的是 JSON 字符串 → 解析成 object → 当 union 用
    const json = JSON.stringify(FIXTURE_WORKER_RAW);
    const ev = JSON.parse(json) as ReviewStreamEvent;
    expect(ev.event).toBe("funnel_stage_worker_raw");

    if (ev.event !== "funnel_stage_worker_raw") {
      throw new Error("narrow 失败");
    }
    const narrowed: FunnelStageWorkerRawEvent = ev;
    expect(narrowed.count).toBe(28);
    expect(Object.keys(narrowed.by_dimension)).toHaveLength(4);
    expect(narrowed.by_dimension.structure).toBe(7);
    expect(narrowed.dropped_unknown_rule_count).toBe(0);
  });

  it("FunnelStageAfterDedupEvent · dropped_count = N0 - N1", () => {
    const ev = JSON.parse(JSON.stringify(FIXTURE_AFTER_DEDUP)) as ReviewStreamEvent;
    if (ev.event !== "funnel_stage_after_dedup") throw new Error("narrow 失败");
    const narrowed: FunnelStageAfterDedupEvent = ev;
    expect(narrowed.count).toBe(22);
    expect(narrowed.dropped_count).toBe(6);
  });

  it("FunnelStageAfterEvidenceVerifyEvent · wiki_mode + authority_distribution", () => {
    const ev = JSON.parse(JSON.stringify(FIXTURE_AFTER_EVIDENCE_VERIFY)) as ReviewStreamEvent;
    if (ev.event !== "funnel_stage_after_evidence_verify") throw new Error("narrow 失败");
    const narrowed: FunnelStageAfterEvidenceVerifyEvent = ev;
    expect(narrowed.count).toBe(18);
    expect(narrowed.wiki_mode).toBe("rich");
    expect(narrowed.authority_distribution.canonical).toBe(12);
    expect(narrowed.retracted_by_reason.no_wiki_match).toBe(2);
  });

  it("FunnelStageAfterGoshawkEvent · delta_breakdown 五桶 + facet_links", () => {
    const ev = JSON.parse(JSON.stringify(FIXTURE_AFTER_GOSHAWK)) as ReviewStreamEvent;
    if (ev.event !== "funnel_stage_after_goshawk") throw new Error("narrow 失败");
    const narrowed: FunnelStageAfterGoshawkEvent = ev;
    expect(narrowed.count).toBe(17);
    // 五桶都存在 (即使值为 0)
    const d = narrowed.delta_breakdown;
    expect(d.removed + d.merged_to_facet + d.added + d.false_positive_restored + d.kept_intact)
      .toBe(17);
    expect(narrowed.facet_links[0]?.facet).toBe("STR-001-A");
    expect(narrowed.facet_links[0]?.primary).toBe("STR-001");
  });

  it("FunnelSummaryEvent · stage_retention 三比率 + suspicious_flags 数组", () => {
    const ev = JSON.parse(JSON.stringify(FIXTURE_FUNNEL_SUMMARY)) as ReviewStreamEvent;
    if (ev.event !== "funnel_summary") throw new Error("narrow 失败");
    const narrowed: FunnelSummaryEvent = ev;
    expect(narrowed.stages.N0_worker_raw).toBe(28);
    expect(narrowed.stage_retention.dedup_retention).toBeCloseTo(0.786, 2);
    expect(Array.isArray(narrowed.suspicious_flags)).toBe(true);
  });

  it("FinalReviewerDoneEvent · 升级带 confidence + DAR retention_kind_dist", () => {
    const ev = JSON.parse(JSON.stringify(FIXTURE_FINAL_REVIEWER_DONE)) as ReviewStreamEvent;
    if (ev.event !== "final_reviewer_done") throw new Error("narrow 失败");
    const narrowed: FinalReviewerDoneEvent = ev;
    expect(narrowed.confidence).toBe(0.85);
    expect(narrowed.empty_retry_used).toBe(false);
    expect(narrowed.retention_kind_dist?.unanimous).toBe(12);
    expect(narrowed.minority_kept).toBe(1);
  });

  it("FinalReviewerDoneEvent · 失败分支只有 error 字段", () => {
    const errPayload = {
      event: "final_reviewer_done",
      progress: 95,
      label: "终审完成",
      error: "goshawk timeout",
    };
    const ev = JSON.parse(JSON.stringify(errPayload)) as ReviewStreamEvent;
    if (ev.event !== "final_reviewer_done") throw new Error("narrow 失败");
    const narrowed: FinalReviewerDoneEvent = ev;
    expect(narrowed.error).toBe("goshawk timeout");
    expect(narrowed.confidence).toBeUndefined();
  });

  it("EvidenceVerifyDoneEvent · 升级带 wiki_mode + authority_distribution", () => {
    const ev = JSON.parse(JSON.stringify(FIXTURE_EVIDENCE_VERIFY_DONE)) as ReviewStreamEvent;
    if (ev.event !== "evidence_verify_done") throw new Error("narrow 失败");
    const narrowed: EvidenceVerifyDoneEvent = ev;
    expect(narrowed.retracted).toBe(3);
    expect(narrowed.wiki_mode).toBe("rich");
    expect(narrowed.authority_distribution?.canonical).toBe(12);
  });

  it("union 7 类全 narrow · runtime + 编译期", () => {
    // SSE 收到的事件流 (mock)
    const stream: ReviewStreamEvent[] = [
      JSON.parse(JSON.stringify(FIXTURE_WORKER_RAW)),
      JSON.parse(JSON.stringify(FIXTURE_AFTER_DEDUP)),
      JSON.parse(JSON.stringify(FIXTURE_AFTER_EVIDENCE_VERIFY)),
      JSON.parse(JSON.stringify(FIXTURE_AFTER_GOSHAWK)),
      JSON.parse(JSON.stringify(FIXTURE_FUNNEL_SUMMARY)),
      JSON.parse(JSON.stringify(FIXTURE_FINAL_REVIEWER_DONE)),
      JSON.parse(JSON.stringify(FIXTURE_EVIDENCE_VERIFY_DONE)),
    ];

    // exhaustiveness: switch 必须覆盖所有 funnel 分支 (TS 编译期会保证)
    let funnel_count = 0;
    for (const ev of stream) {
      switch (ev.event) {
        case "funnel_stage_worker_raw":
        case "funnel_stage_after_dedup":
        case "funnel_stage_after_evidence_verify":
        case "funnel_stage_after_goshawk":
        case "funnel_summary":
        case "final_reviewer_done":
        case "evidence_verify_done":
          funnel_count++;
          break;
        default:
          // 其他 event (uploaded / wiki_scanned / worker_done ...) 不计 funnel
          break;
      }
    }
    expect(funnel_count).toBe(7);
  });
});
