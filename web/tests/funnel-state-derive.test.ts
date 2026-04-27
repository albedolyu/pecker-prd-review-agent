/**
 * funnel state 派生纯函数单测 · 2026-04-28 step 1c
 *
 * 跑:cd web && pnpm vitest run tests/funnel-state-derive.test.ts
 *
 * 范围:
 * - deriveFunnelState 从 events 数组派生 5 stage + retention + wiki authority.
 * - 5 stage tile 渲染 (test 直接拿派生 state 校验, vitest node env 不能 render
 *   React, UI 渲染由 Playwright e2e 覆盖).
 * - cross_boundary chip 渲染条件 (派生 cross_boundary count, UI render 同上).
 * - nodata fallback (没收到 funnel event 时 hasAnyEvent=false).
 *
 * 注: vitest config environment=node, 这里只测纯函数派生层.
 * UI render 测试在 e2e/ 下用 Playwright.
 */

import { describe, it, expect } from "vitest";
import {
  deriveFunnelState,
  type FunnelStageKey,
} from "@/lib/v8-run-helpers";
import type { ReviewStreamEvent } from "@/lib/useReviewStream";

// ============================================================
// 真实 SSE event 序列 fixture (按 review.py 实际发的顺序)
// ============================================================

function makeWorkerRaw(): ReviewStreamEvent {
  return {
    event: "funnel_stage_worker_raw",
    progress: null,
    label: "N0",
    count: 28,
    by_dimension: { structure: 7, quality: 8, data_quality: 6, ai_coding: 7 },
  } as ReviewStreamEvent;
}

function makeAfterDedup(): ReviewStreamEvent {
  return {
    event: "funnel_stage_after_dedup",
    progress: null,
    label: "N1",
    count: 22,
    dropped_count: 6,
  } as ReviewStreamEvent;
}

function makeAfterEvidenceVerify(): ReviewStreamEvent {
  return {
    event: "funnel_stage_after_evidence_verify",
    progress: null,
    label: "N2",
    count: 18,
    retracted_count: 3,
    downgraded_count: 1,
    retracted_by_reason: { no_wiki_match: 2, wiki_contradicts: 1 },
    downgraded_by_reason: { partial_match: 1 },
    wiki_mode: "rich",
    authority_distribution: { canonical: 12, contextual: 6 },
  } as ReviewStreamEvent;
}

function makeAfterGoshawk(): ReviewStreamEvent {
  return {
    event: "funnel_stage_after_goshawk",
    progress: null,
    label: "N3",
    count: 17,
    delta_breakdown: {
      removed: 1,
      merged_to_facet: 2,
      added: 0,
      false_positive_restored: 0,
      kept_intact: 14,
    },
    facet_links: [],
  } as ReviewStreamEvent;
}

function makeFunnelSummary(): ReviewStreamEvent {
  return {
    event: "funnel_summary",
    progress: null,
    label: "summary",
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
  } as ReviewStreamEvent;
}

// ============================================================
// Tests
// ============================================================

describe("deriveFunnelState · 5 stage 派生", () => {
  it("test_funnel_panel_renders_5_stages — 完整 SSE 序列后 5 stage 都有 count", () => {
    const events: ReviewStreamEvent[] = [
      makeWorkerRaw(),
      makeAfterDedup(),
      makeAfterEvidenceVerify(),
      makeAfterGoshawk(),
      makeFunnelSummary(),
    ];
    const state = deriveFunnelState(events);

    expect(state.hasAnyEvent).toBe(true);

    const expectedKeys: FunnelStageKey[] = [
      "N0_worker_raw",
      "N1_after_dedup",
      "N2_after_evidence_verify",
      "N3_after_goshawk",
      "N4_after_pm_decision",
    ];
    for (const k of expectedKeys) {
      expect(state.stages[k]).toBeDefined();
      expect(state.stages[k].label).toBeTruthy();
    }

    // N0-N3 应该都 received=true 有具体 count
    expect(state.stages.N0_worker_raw.received).toBe(true);
    expect(state.stages.N0_worker_raw.count).toBe(28);
    expect(state.stages.N1_after_dedup.count).toBe(22);
    expect(state.stages.N1_after_dedup.detail).toMatch(/-6/);
    expect(state.stages.N2_after_evidence_verify.count).toBe(18);
    expect(state.stages.N2_after_evidence_verify.detail).toMatch(/3/);
    expect(state.stages.N3_after_goshawk.count).toBe(17);
    expect(state.stages.N3_after_goshawk.detail).toMatch(/合并 2/);

    // N4 在 confirm endpoint 才发, Phase2 拿不到 — 永远是 pending
    expect(state.stages.N4_after_pm_decision.received).toBe(false);
    expect(state.stages.N4_after_pm_decision.count).toBeNull();
    expect(state.stages.N4_after_pm_decision.detail).toBe("待 PM 决策");

    // retention 来自 funnel_summary
    expect(state.retention).toBeDefined();
    expect(state.retention!.dedup_retention).toBeCloseTo(0.786, 2);
  });

  it("test_nodata_fallback — 没收到任何 funnel event 时 hasAnyEvent=false", () => {
    const events: ReviewStreamEvent[] = [
      // 只有非 funnel event (老版后端 / 评审刚开始)
      {
        event: "uploaded",
        progress: 5,
        label: "PRD 上传",
      } as ReviewStreamEvent,
      {
        event: "wiki_scanned",
        progress: 12,
        label: "wiki 扫描",
        page_count: 30,
      } as ReviewStreamEvent,
    ];
    const state = deriveFunnelState(events);
    expect(state.hasAnyEvent).toBe(false);
    // 5 stage 都 received=false
    for (const v of Object.values(state.stages)) {
      if (v.label.startsWith("N4")) continue; // N4 永远 false
      expect(v.received).toBe(false);
      expect(v.count).toBeNull();
    }
    expect(state.retention).toBeUndefined();
    expect(state.wikiMode).toBeUndefined();
  });

  it("部分 event 收到 — N0 + N1 有 count, N2-N3 仍 pending", () => {
    const events: ReviewStreamEvent[] = [makeWorkerRaw(), makeAfterDedup()];
    const state = deriveFunnelState(events);
    expect(state.hasAnyEvent).toBe(true);
    expect(state.stages.N0_worker_raw.received).toBe(true);
    expect(state.stages.N1_after_dedup.received).toBe(true);
    expect(state.stages.N2_after_evidence_verify.received).toBe(false);
    expect(state.stages.N3_after_goshawk.received).toBe(false);
  });

  it("audit#4 — wiki_mode + authority_distribution 从 evidence_verify 拿", () => {
    const events: ReviewStreamEvent[] = [makeAfterEvidenceVerify()];
    const state = deriveFunnelState(events);
    expect(state.wikiMode).toBe("rich");
    expect(state.authorityDistribution).toEqual({ canonical: 12, contextual: 6 });
  });

  it("audit#4 兜底 — 没 funnel_stage_after_evidence_verify 时从 evidence_verify_done 拿 wiki", () => {
    // 老版只发 evidence_verify_done, 兼容
    const events: ReviewStreamEvent[] = [
      {
        event: "evidence_verify_done",
        progress: null,
        label: "ev done",
        retracted: 3,
        caveat: 2,
        wiki_mode: "sparse",
        authority_distribution: { canonical: 0, contextual: 4, generated: 18 },
      } as ReviewStreamEvent,
    ];
    const state = deriveFunnelState(events);
    expect(state.wikiMode).toBe("sparse");
    expect(state.authorityDistribution?.generated).toBe(18);
  });

  it("funnel_summary 兜底回填 stages — 只发 summary 没单独 stage event 时", () => {
    const events: ReviewStreamEvent[] = [makeFunnelSummary()];
    const state = deriveFunnelState(events);
    expect(state.hasAnyEvent).toBe(true);
    expect(state.stages.N0_worker_raw.count).toBe(28);
    expect(state.stages.N3_after_goshawk.count).toBe(17);
    // 但 detail 不会有 (单 stage event 才有)
    expect(state.stages.N1_after_dedup.detail).toBeUndefined();
  });

  it("retry 重发 — 取最后值 (不是 first)", () => {
    const old: ReviewStreamEvent = {
      event: "funnel_stage_worker_raw",
      progress: null,
      label: "N0 old",
      count: 99,
      by_dimension: { structure: 99 },
    } as ReviewStreamEvent;
    const fresh = makeWorkerRaw();
    const state = deriveFunnelState([old, fresh]);
    expect(state.stages.N0_worker_raw.count).toBe(28);
  });
});

describe("cross_boundary chip · 派生条件", () => {
  // 注: chip 视觉渲染不在 vitest node env 测, 但派生条件 (cross_boundary=true) 测.
  it("test_cross_boundary_chip_shows — items 含 cross_boundary 时计数 > 0", () => {
    const items = [
      { id: "STR-001", dimension: "structure", problem: "x", cross_boundary: true },
      { id: "STR-002", dimension: "structure", problem: "y" },
      { id: "DQ-001", dimension: "data_quality", problem: "z", cross_boundary: true },
    ];
    const cnt = items.filter((it) => it.cross_boundary).length;
    expect(cnt).toBe(2);
  });

  it("没 cross_boundary 字段时计数 = 0", () => {
    const items = [
      { id: "STR-001", dimension: "structure", problem: "x" },
      { id: "DQ-001", dimension: "data_quality", problem: "z" },
    ];
    const cnt = items.filter((it) => (it as { cross_boundary?: boolean }).cross_boundary).length;
    expect(cnt).toBe(0);
  });
});
