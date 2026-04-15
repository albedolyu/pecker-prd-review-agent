"use client";

/**
 * ForestLanding — 赛博童话森林首页
 *
 * Canvas 2D 画"数字雨"组成的森林:
 * - 每一列是一串从上向下滴落的字符(混合 0/1、中文数字、hex)
 * - 字符色为几档 emerald 绿,速度和透明度随列不同,模拟"树与树的深浅"
 * - 中间留出一个树洞空洞,树洞里放一只巨大的啄木鸟 emoji 在轻微呼吸
 * - 最下面"垂下来的藤蔓"串着 3 个入口选项,点击跳转
 *
 * 本组件不依赖任何后端,/api/me 也不在这里调用 —— 所以它可以作为
 * 未登录用户的第一眼。点击"进入编辑部"再去 /login 完成登录。
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { WoodpeckerArt } from "@/components/birds/BirdArt";

// 数字雨候选字符集:0/1 + 中文数字 + hex + 简单符号。
// 要让它像"数字组成的森林",关键是 0/1 和 hex 占大头,中文数字点缀。
const RAIN_GLYPHS =
  "01010101010101010101ABCDEF01234567890123456789零一二三四五六七八九十·※◇";

function pickGlyph(): string {
  return RAIN_GLYPHS[Math.floor(Math.random() * RAIN_GLYPHS.length)];
}

// 每一"列"的状态:当前滴到的 y 位置 + 速度 + 透明度 + 颜色档
interface RainColumn {
  x: number;
  y: number; // 最新字符的 y,单位 px
  speed: number; // 每帧下落 px
  alpha: number; // 头部字符透明度
  hueShift: number; // 0=最深绿 1=最亮绿
}

export function ForestLanding() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const router = useRouter();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // ============ Canvas matrix 数字雨 ============
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let columns: RainColumn[] = [];
    let rafId = 0;
    const fontSize = 16; // 字符格大小
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    function resize() {
      if (!canvas || !ctx) return;
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // 每列之间 fontSize 间距
      const colCount = Math.ceil(width / fontSize);
      columns = new Array(colCount).fill(0).map((_, i) => ({
        x: i * fontSize,
        // 初始分布 60% 在屏幕内 + 40% 在屏幕外上方,第一帧就有密度
        y:
          Math.random() < 0.6
            ? Math.random() * height
            : Math.random() * -height * 0.8,
        speed: 0.9 + Math.random() * 1.6,
        alpha: 0.65 + Math.random() * 0.35,
        hueShift: Math.random(),
      }));
    }

    // 中央树洞 —— 圆形 clip 区域,这里不画数字,让中心干净
    function drawFrame() {
      if (!ctx) return;
      // 半透明黑叠底,拉出拖尾效果 —— 更轻一点让 trail 存活更久
      ctx.fillStyle = "rgba(6, 14, 10, 0.09)";
      ctx.fillRect(0, 0, width, height);

      ctx.font = `${fontSize}px "JetBrains Mono", "Geist Mono", ui-monospace, monospace`;
      ctx.textBaseline = "top";

      const cx = width / 2;
      const cy = height / 2;
      // 中心树洞半径 —— 比屏幕短边的 1/4 稍大
      const holeRadius = Math.min(width, height) * 0.22;
      const holeRsq = holeRadius * holeRadius;

      for (const col of columns) {
        // 距中心的距离,用来判断是否在树洞范围内(树洞内不画)
        const dx = col.x - cx;
        const trailY = col.y;
        const dy = trailY - cy;
        const distSq = dx * dx + dy * dy;
        const inHole = distSq < holeRsq;

        if (!inHole && trailY > -fontSize && trailY < height + fontSize) {
          // 头部字符:近白光绿
          const head = pickGlyph();
          // hue 150-168,接近 emerald 400
          const hue = 150 + col.hueShift * 18;
          const headLight = 72 + col.hueShift * 14;
          ctx.fillStyle = `hsla(${hue}, 82%, ${headLight}%, ${Math.min(1, col.alpha)})`;
          ctx.fillText(head, col.x, trailY);
        }

        // 拖尾:向上 14 个字符,透明度递减,颜色更暗
        for (let t = 1; t < 14; t++) {
          const y = trailY - t * fontSize;
          if (y < -fontSize) break;
          if (y > height) continue;
          // 确定此 y 是否在树洞内
          const tdy = y - cy;
          if (dx * dx + tdy * tdy < holeRsq) continue;
          const fade = 1 - t / 14;
          const a = col.alpha * fade * fade * 0.85;
          const hue = 150 + col.hueShift * 18;
          const lt = 40 + col.hueShift * 22 + fade * 10;
          ctx.fillStyle = `hsla(${hue}, 72%, ${lt}%, ${a})`;
          ctx.fillText(pickGlyph(), col.x, y);
        }

        col.y += col.speed * fontSize * 0.32;
        if (col.y > height + fontSize * 14) {
          col.y = -Math.random() * height * 0.3 - fontSize * 4;
          col.speed = 0.9 + Math.random() * 1.6;
          col.alpha = 0.65 + Math.random() * 0.35;
          col.hueShift = Math.random();
        }
      }

      // 中央树洞 —— 两圈光晕,让中心有呼吸感
      const holeGrad = ctx.createRadialGradient(
        cx,
        cy,
        holeRadius * 0.3,
        cx,
        cy,
        holeRadius * 1.2,
      );
      holeGrad.addColorStop(0, "rgba(8, 20, 14, 1)");
      holeGrad.addColorStop(0.6, "rgba(8, 20, 14, 0.85)");
      holeGrad.addColorStop(1, "rgba(8, 20, 14, 0)");
      ctx.fillStyle = holeGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, holeRadius * 1.2, 0, Math.PI * 2);
      ctx.fill();

      // 树洞内圈描边 —— 淡绿发光轮廓,像屏幕 CRT 圈
      ctx.strokeStyle = "rgba(120, 230, 170, 0.45)";
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(cx, cy, holeRadius * 0.95, 0, Math.PI * 2);
      ctx.stroke();

      ctx.strokeStyle = "rgba(120, 230, 170, 0.18)";
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      ctx.arc(cx, cy, holeRadius * 1.04, 0, Math.PI * 2);
      ctx.stroke();

      rafId = requestAnimationFrame(drawFrame);
    }

    // 初始全黑底
    ctx.fillStyle = "rgba(6, 14, 10, 1)";
    resize();
    ctx.fillRect(0, 0, width, height);
    drawFrame();

    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-[#060e0a] text-emerald-50">
      {/* ============ 数字雨 canvas ============ */}
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 h-full w-full"
        aria-hidden
      />

      {/* ============ 顶部刊头(刺头细字,贴森林顶) ============ */}
      <header className="pointer-events-none absolute left-0 right-0 top-0 z-10 flex items-center gap-4 px-8 pt-6 font-mono text-[10px] uppercase tracking-[0.24em] text-emerald-200/70">
        <span>啄 · 木 · 鸟</span>
        <span className="h-px flex-1 bg-emerald-200/30" />
        <span>第 壹 期 · 森林版</span>
        <span className="h-px flex-1 bg-emerald-200/30" />
        <span>MMXXVI</span>
      </header>

      {/* ============ 树洞中心:啄木鸟 emoji + 呼吸光晕 ============ */}
      <div
        className={`absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 transition-opacity duration-1000 ${
          mounted ? "opacity-100" : "opacity-0"
        }`}
      >
        {/* 轻微呼吸的圆环光 */}
        <span
          className="pointer-events-none absolute left-1/2 top-1/2 h-[22rem] w-[22rem] -translate-x-1/2 -translate-y-1/2 animate-pulse rounded-full bg-emerald-500/5 blur-3xl"
          aria-hidden
        />
        <div className="relative flex flex-col items-center gap-6">
          {/* 大号啄木鸟 —— 从数字森林里探出头,SVG 手绘组件,自己的灵魂 */}
          <div className="relative">
            {/* 呼吸光晕 */}
            <span
              className="pointer-events-none absolute left-1/2 top-1/2 h-44 w-44 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-400/15 blur-2xl"
              aria-hidden
            />
            {/* 轮廓圈 —— 像树洞里透出的光 */}
            <span
              className="pointer-events-none absolute left-1/2 top-1/2 h-52 w-52 -translate-x-1/2 -translate-y-1/2 rounded-full border border-emerald-300/35"
              aria-hidden
            />
            <div
              className="pointer-events-none relative animate-[peckBreath_5.2s_ease-in-out_infinite]"
              style={{
                filter:
                  "drop-shadow(0 0 22px rgba(52,211,153,0.45)) drop-shadow(0 3px 0 rgba(0,0,0,0.35))",
              }}
              aria-hidden
            >
              <WoodpeckerArt size={186} />
            </div>
          </div>

          {/* 刊名:衬线大字,微光效果 */}
          <div className="text-center">
            <h1 className="font-serif text-[clamp(2.4rem,6vw,4.2rem)] font-medium leading-[0.98] tracking-tight text-emerald-50 [font-variation-settings:'opsz'_144,'SOFT'_100,'WONK'_1] drop-shadow-[0_0_20px_rgba(52,211,153,0.35)]">
              啄木鸟
            </h1>
            <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.32em] text-emerald-200/65">
              a forest that reviews your PRD
            </div>
            <p className="mx-auto mt-3 max-w-[24rem] font-serif text-[13.5px] italic leading-[1.7] text-emerald-100/70 [font-variation-settings:'opsz'_144,'SOFT'_100,'WONK'_1]">
              一只鸟加无数次回声,比一百只鸟凭直觉乱啄,要可靠得多。
            </p>
          </div>
        </div>
      </div>

      {/* ============ 底部垂下来的"藤蔓" + 3 个入口 ============ */}
      <nav
        className={`absolute bottom-0 left-1/2 z-10 -translate-x-1/2 pb-10 transition-opacity delay-500 duration-1000 ${
          mounted ? "opacity-100" : "opacity-0"
        }`}
        aria-label="入口"
      >
        {/* 藤蔓线 —— 从屏幕中部垂下来,到选项顶端结束 */}
        <svg
          className="pointer-events-none absolute left-1/2 -top-40 h-40 w-8 -translate-x-1/2"
          viewBox="0 0 32 160"
          fill="none"
          aria-hidden
        >
          {/* 弯曲的藤蔓 */}
          <path
            d="M 16 0 C 10 30, 22 60, 14 90 S 18 130, 16 160"
            stroke="rgba(120, 230, 170, 0.55)"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
          {/* 几片小叶子 */}
          <ellipse
            cx="8"
            cy="36"
            rx="5"
            ry="2.4"
            fill="rgba(110, 220, 160, 0.5)"
            transform="rotate(-24 8 36)"
          />
          <ellipse
            cx="22"
            cy="72"
            rx="5.5"
            ry="2.6"
            fill="rgba(120, 230, 170, 0.55)"
            transform="rotate(22 22 72)"
          />
          <ellipse
            cx="10"
            cy="112"
            rx="4.5"
            ry="2.2"
            fill="rgba(100, 210, 150, 0.5)"
            transform="rotate(-18 10 112)"
          />
        </svg>

        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.28em] text-emerald-200/55">
            <span className="h-px w-6 bg-emerald-200/35" />
            进 入 森 林
            <span className="h-px w-6 bg-emerald-200/35" />
          </div>
          <div className="flex flex-wrap items-stretch justify-center gap-3">
            <EntryLeaf
              label="进入编辑部"
              hint="登录 · 今日评审"
              primary
              onClick={() => router.push("/login")}
            />
            <EntryLeaf
              label="直接去评审"
              hint="若已登录"
              onClick={() => router.push("/review")}
            />
            <EntryLeaf
              label="家族名册"
              hint="认识十只鸟"
              onClick={() => router.push("/about")}
            />
          </div>
        </div>
      </nav>

      {/* 底部一行脚注:Phase F · 版次 */}
      <footer
        className="pointer-events-none absolute bottom-2 left-0 right-0 z-10 text-center font-mono text-[9px] uppercase tracking-[0.22em] text-emerald-200/35"
        aria-hidden
      >
        phase f · 第壹期 · 森林深处敲第一下
      </footer>

      {/* peckBreath 呼吸动画 —— 局部 keyframes,避免污染 globals.css */}
      <style>{`
        @keyframes peckBreath {
          0%, 100% { transform: translateY(0) rotate(0); }
          35% { transform: translateY(-3px) rotate(-1.5deg); }
          55% { transform: translateY(1.5px) rotate(1.2deg); }
          78% { transform: translateY(-1px) rotate(-0.6deg); }
        }
      `}</style>
    </div>
  );
}

// ============================================================
// EntryLeaf —— 悬在藤蔓末端的"叶子"按钮
// ============================================================
interface EntryLeafProps {
  label: string;
  hint: string;
  primary?: boolean;
  onClick: () => void;
}

function EntryLeaf({ label, hint, primary, onClick }: EntryLeafProps) {
  return (
    <button
      onClick={onClick}
      className={`group relative min-w-[9rem] overflow-hidden rounded-[2px] px-5 py-3 text-left font-serif transition-all duration-300 [font-variation-settings:'opsz'_144,'SOFT'_100,'WONK'_1] ${
        primary
          ? "border border-emerald-300/60 bg-emerald-400/12 text-emerald-50 shadow-[0_0_18px_rgba(52,211,153,0.25)] hover:bg-emerald-400/22 hover:shadow-[0_0_24px_rgba(52,211,153,0.45)]"
          : "border border-emerald-200/30 bg-emerald-900/20 text-emerald-100/85 hover:border-emerald-200/55 hover:bg-emerald-900/35"
      }`}
    >
      {/* 叶脉装饰线 */}
      <span
        className="pointer-events-none absolute right-3 top-1/2 h-[1px] w-4 -translate-y-1/2 bg-emerald-200/35 transition-all duration-300 group-hover:w-6 group-hover:bg-emerald-200/70"
        aria-hidden
      />
      <div className="text-[15px] italic leading-[1.1]">{label}</div>
      <div className="mt-[2px] font-mono text-[9px] uppercase not-italic tracking-[0.18em] text-emerald-200/55">
        {hint}
      </div>
    </button>
  );
}
