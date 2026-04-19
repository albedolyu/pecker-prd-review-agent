/**
 * BirdArt v2 —— 十只鸟 · 纯线稿版
 *
 * 和 v1 (BirdArt.tsx) 的差别:
 * - 统一 viewBox 100x100, stroke 1.6-1.8
 * - 去除填色方块,改为"轮廓线 + 1-2 处识别色块 + 墨点眼"
 * - 每只有独特剪影(姿态/尾型/比例),遮住道具也能认出来
 * - 颜色统一用 globals.css 的 Pecker token:
 *     --color-foreground (#3a4238) · 墨线
 *     --pecker-rose (#c98e7f)      · 红冠 / 柔绯
 *     --pecker-amber (#d4a05e)     · 喙 / 线团
 *     --pecker-moss-deep (#5d7357) · 辅助绿
 *
 * 接口完全兼容 v1 BirdArtProps,可直接替换:
 *     import { BIRD_ART_V2 } from "@/components/birds/BirdArt-v2";
 *     const Art = BIRD_ART_V2[role.key];
 *     <Art size={88} />
 */

import type { RoleKey } from "@/lib/roles";

interface BirdArtProps {
  size?: number;
  className?: string;
}

const SVG_CLASS = "pointer-events-none select-none";

// 色板 · 和 globals.css token 对齐
const C = {
  ink: "#3a4238",
  inkDeep: "#2a3028",
  paper: "#eef2e5",
  rose: "#c98e7f",
  amber: "#d4a05e",
  amberDark: "#6b4e32",
  moss: "#5d7357",
  mossLight: "#8ba888",
  sky: "#a8bac0",
} as const;

// ============================================================
// 01 · WoodpeckerArt v2 — 啄木鸟 · 主编
// 特征: 红冠 + 橙喙 + 栖树姿
// ============================================================
export function WoodpeckerArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <path
        d="M 65 28 Q 74 29, 78 37 Q 83 39, 85 40 Q 83 42, 78 42 Q 74 44, 69 44 Q 64 48, 60 54 Q 69 57, 74 64 Q 74 72, 65 75 L 54 77 L 54 85 M 44 85 L 44 77 Q 36 75, 31 69 Q 28 60, 31 51 Q 34 44, 41 40 Q 46 39, 52 39 Q 56 36, 59 31 Q 62 28, 65 28 Z"
        stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinejoin="round" strokeLinecap="round"
      />
      <path d="M 59 28 Q 62 20,66 25" stroke={C.rose} strokeWidth="3" fill="none" strokeLinecap="round" />
      <path d="M 63 23 L 64 17" stroke={C.rose} strokeWidth="2.8" strokeLinecap="round" />
      <path d="M 67 26 Q 71 19,74 28" stroke={C.rose} strokeWidth="3" fill="none" strokeLinecap="round" />
      <circle cx="67" cy="36" r="2" fill={C.ink} />
      <path d="M 76 40 L 88 41 L 77 44" stroke={C.amber} strokeWidth="1.8" fill="none" strokeLinejoin="round" />
      <path d="M 42 52 Q 38 62,44 72" stroke={C.ink} strokeWidth="1.1" fill="none" strokeLinecap="round" opacity="0.7" />
    </svg>
  );
}

// ============================================================
// 02 · WeaverArt v2 — 织布鸟 · 责编
// 特征: 分叉短尾 + 黄冠 + 栖横枝 + 线团
// ============================================================
export function WeaverArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <path
        d="M 48 32 Q 62 30,68 38 Q 75 40,78 42 Q 74 44,68 44 Q 62 48,58 54 Q 70 58,70 66 L 82 72 M 70 66 Q 66 72,60 74 L 42 74 Q 28 72,26 60 Q 26 48,34 42 Q 42 36,48 32 Z"
        stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinejoin="round" strokeLinecap="round"
      />
      <path d="M 70 66 L 88 70 M 70 66 L 86 78" stroke={C.ink} strokeWidth="1.4" fill="none" strokeLinecap="round" />
      <path d="M 48 32 Q 58 26,68 34" stroke={C.amber} strokeWidth="3.5" fill="none" strokeLinecap="round" />
      <circle cx="56" cy="40" r="1.8" fill={C.ink} />
      <path d="M 68 42 L 78 43 L 69 46 Z" stroke={C.amberDark} strokeWidth="1.5" fill="none" strokeLinejoin="round" />
      {/* 线团 */}
      <circle cx="20" cy="82" r="5" fill="none" stroke={C.rose} strokeWidth="1.2" />
      <path d="M 16 80 Q 20 84,24 80" stroke={C.rose} strokeWidth="0.7" fill="none" />
      <line x1="25" y1="80" x2="38" y2="66" stroke={C.rose} strokeWidth="0.9" strokeLinecap="round" opacity="0.7" />
    </svg>
  );
}

// ============================================================
// 03 · OwlArt v2 — 猫头鹰 · 审校
// 特征: 圆盘脸 + 尖耳 + 眼镜 + 肚斑
// ============================================================
export function OwlArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <path d="M 50 22 Q 74 24,78 50 Q 76 78,50 84 Q 24 78,22 50 Q 26 24,50 22 Z" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinejoin="round" />
      <path d="M 32 30 L 34 20 L 42 32" stroke={C.ink} strokeWidth="1.4" fill="none" strokeLinejoin="round" />
      <path d="M 68 30 L 66 20 L 58 32" stroke={C.ink} strokeWidth="1.4" fill="none" strokeLinejoin="round" />
      <circle cx="38" cy="45" r="9" stroke={C.ink} strokeWidth="1.3" fill="none" />
      <circle cx="62" cy="45" r="9" stroke={C.ink} strokeWidth="1.3" fill="none" />
      <line x1="47" y1="45" x2="53" y2="45" stroke={C.ink} strokeWidth="1" />
      <circle cx="38" cy="45" r="2" fill={C.ink} />
      <circle cx="62" cy="45" r="2" fill={C.ink} />
      <path d="M 46 55 L 50 62 L 54 55" stroke={C.amber} strokeWidth="1.6" fill="none" strokeLinejoin="round" />
      <circle cx="42" cy="68" r="1" fill={C.ink} opacity="0.5" />
      <circle cx="58" cy="68" r="1" fill={C.ink} opacity="0.5" />
      <circle cx="50" cy="74" r="1" fill={C.ink} opacity="0.5" />
    </svg>
  );
}

// ============================================================
// 04 · RavenArt v2 — 渡鸦 · 技术编辑
// 特征: 瘦长身 + 翘尾 + 钢笔
// ============================================================
export function RavenArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <path
        d="M 36 36 Q 48 34,58 38 Q 68 42,72 50 Q 78 54,86 52 L 82 60 Q 74 58,68 58 Q 76 68,86 72 L 82 80 Q 68 78,60 72 L 50 70 L 46 78 L 40 78 L 44 68 Q 30 64,26 52 Q 24 42,36 36 Z"
        stroke={C.inkDeep} strokeWidth="1.6" fill="none" strokeLinejoin="round" strokeLinecap="round"
      />
      <path d="M 40 48 Q 38 54,42 60" stroke={C.inkDeep} strokeWidth="1" fill="none" strokeLinecap="round" opacity="0.7" />
      <path d="M 46 50 Q 44 56,48 62" stroke={C.inkDeep} strokeWidth="0.8" fill="none" strokeLinecap="round" opacity="0.6" />
      <circle cx="40" cy="42" r="2" fill={C.ink} />
      <circle cx="40.6" cy="41" r="0.5" fill="#fff" />
      <path d="M 30 43 L 18 45 L 29 47" stroke={C.inkDeep} strokeWidth="1.8" fill="none" strokeLinejoin="round" />
      <g transform="translate(14,43) rotate(-8)">
        <rect x="-6" y="0" width="12" height="2.2" rx="1" fill="none" stroke="#5c6158" strokeWidth="1" />
        <rect x="-6" y="0" width="3.5" height="2.2" rx="1" fill={C.rose} />
        <path d="M 6 0 L 9 1.1 L 6 2.2" fill={C.amber} />
      </g>
    </svg>
  );
}

// ============================================================
// 05 · CormorantArt v2 — 鸬鹚 · 数据核对员
// 特征: S 形长颈 + 站水边 + 翅膀半张晾干
// ============================================================
export function CormorantArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <path d="M 40 58 Q 56 54,68 60 Q 76 66,74 74 Q 70 80,56 80 L 38 80 Q 28 80,28 74 Q 28 64,40 58 Z" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinejoin="round" />
      <path d="M 56 54 Q 52 42,58 34 Q 66 28,72 30 Q 76 34,72 40" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinecap="round" />
      <ellipse cx="76" cy="30" rx="8" ry="6" fill="none" stroke={C.ink} strokeWidth="1.6" />
      <path d="M 82 30 L 96 32 Q 96 34,94 35" stroke={C.amber} strokeWidth="1.8" fill="none" strokeLinecap="round" />
      <circle cx="78" cy="28" r="1.5" fill={C.ink} />
      <path d="M 36 62 Q 24 66,16 80 M 40 66 Q 28 72,22 82" stroke={C.ink} strokeWidth="1.3" fill="none" strokeLinecap="round" />
      <path d="M 8 88 Q 30 86,52 88 Q 74 90,94 88" stroke={C.sky} strokeWidth="1.2" fill="none" strokeLinecap="round" />
      <circle cx="20" cy="84" r="1" fill="none" stroke={C.sky} strokeWidth="0.8" />
      <circle cx="78" cy="84" r="1" fill="none" stroke={C.sky} strokeWidth="0.8" />
    </svg>
  );
}

// ============================================================
// 06 · GoshawkArt v2 — 苍鹰 · 终审
// 特征: 大型猛禽 + 钩喙 + 单片眼镜 + 翅膀纹
// ============================================================
export function GoshawkArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <path
        d="M 56 22 Q 72 22,78 36 Q 80 40,82 42 Q 80 44,76 44 Q 72 46,68 48 Q 72 56,76 66 Q 78 78,66 84 L 54 86 L 54 94 M 46 94 L 46 86 Q 28 80,24 64 Q 24 48,32 40 Q 42 34,50 32 Q 54 26,56 22 Z"
        stroke={C.ink} strokeWidth="1.8" fill="none" strokeLinejoin="round" strokeLinecap="round"
      />
      <path d="M 72 42 Q 84 42,86 46 Q 84 48,80 46" stroke={C.amber} strokeWidth="1.8" fill="none" strokeLinejoin="round" />
      <circle cx="62" cy="38" r="6" stroke={C.ink} strokeWidth="1.3" fill="none" />
      <line x1="57" y1="43" x2="52" y2="50" stroke={C.ink} strokeWidth="1" strokeLinecap="round" />
      <circle cx="62" cy="38" r="1.8" fill={C.ink} />
      <path d="M 36 50 Q 30 64,38 76" stroke={C.ink} strokeWidth="1" fill="none" strokeLinecap="round" opacity="0.65" />
      <path d="M 32 56 Q 28 68,34 76" stroke={C.ink} strokeWidth="0.8" fill="none" opacity="0.5" />
    </svg>
  );
}

// ============================================================
// 07 · CuckooArt v2 — 杜鹃 · 试读员 / 质量门禁
// 特征: 超长尾 + 肚纹 + 印章
// ============================================================
export function CuckooArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <ellipse cx="26" cy="38" rx="9" ry="7" fill="none" stroke={C.ink} strokeWidth="1.6" />
      <path d="M 34 42 Q 46 40,56 44 Q 62 48,64 54" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinecap="round" />
      <path d="M 34 44 Q 48 48,60 52 Q 66 58,68 62" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinecap="round" />
      {/* 超长尾 */}
      <path d="M 64 54 Q 78 58,92 66" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinecap="round" />
      <path d="M 64 58 Q 76 64,88 72" stroke={C.ink} strokeWidth="1.4" fill="none" strokeLinecap="round" />
      <path d="M 66 62 Q 74 68,82 76" stroke={C.ink} strokeWidth="1.2" fill="none" strokeLinecap="round" />
      {/* 肚纹 */}
      <line x1="36" y1="48" x2="52" y2="50" stroke={C.ink} strokeWidth="0.8" opacity="0.55" />
      <line x1="38" y1="51" x2="54" y2="53" stroke={C.ink} strokeWidth="0.8" opacity="0.55" />
      <circle cx="23" cy="36" r="1.5" fill={C.ink} />
      <path d="M 17 39 L 10 40 L 17 41" stroke={C.amber} strokeWidth="1.4" fill="none" strokeLinejoin="round" />
      {/* 印章 */}
      <g transform="translate(10,78)">
        <rect x="0" y="0" width="12" height="3.5" rx="0.4" fill="none" stroke={C.ink} strokeWidth="1" />
        <rect x="2" y="-5" width="8" height="5" fill="none" stroke={C.ink} strokeWidth="1" />
        <circle cx="6" cy="1.8" r="1" fill="#b85c4a" />
      </g>
    </svg>
  );
}

// ============================================================
// 08 · KakapoArt v2 — 鸮鹦鹉 · 资料员 / 知识库
// 特征: 最圆胖 + 头顶绒毛 + 坐书堆
// ============================================================
export function KakapoArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <path d="M 50 24 Q 78 28,82 52 Q 82 78,60 86 L 40 86 Q 18 78,18 52 Q 22 28,50 24 Z" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinejoin="round" />
      {/* 头顶绒毛 */}
      <path d="M 36 28 Q 40 22,46 28 M 50 25 Q 54 20,58 26 M 62 27 Q 66 22,68 28" stroke={C.moss} strokeWidth="1.2" fill="none" strokeLinecap="round" />
      <circle cx="38" cy="48" r="8" stroke={C.ink} strokeWidth="1" fill="none" opacity="0.8" />
      <circle cx="62" cy="48" r="8" stroke={C.ink} strokeWidth="1" fill="none" opacity="0.8" />
      <circle cx="38" cy="48" r="1.8" fill={C.ink} />
      <circle cx="62" cy="48" r="1.8" fill={C.ink} />
      <path d="M 46 56 L 50 62 L 54 56" stroke={C.amber} strokeWidth="1.4" fill="none" strokeLinejoin="round" />
      {/* 书堆 */}
      <g transform="translate(60,78)">
        <rect x="0" y="0" width="16" height="2.5" fill="none" stroke="#8a4d3e" strokeWidth="0.9" />
        <rect x="1" y="-3" width="14" height="3" fill="none" stroke={C.rose} strokeWidth="0.9" />
        <rect x="0" y="-6" width="16" height="3" fill="none" stroke="#6b8591" strokeWidth="0.9" />
      </g>
    </svg>
  );
}

// ============================================================
// 09 · DoveArt v2 — 信鸽 · 读者反馈
// 特征: 鼓胸 + 扇形尾 + 低头前行 + 信卷
// ============================================================
export function DoveArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      <path d="M 50 38 Q 66 40,72 54 Q 72 66,64 72 L 56 74 Q 42 72,36 64 Q 32 56,36 48 Q 42 40,50 38 Z" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinejoin="round" />
      <path d="M 44 50 Q 40 58,44 66" stroke={C.ink} strokeWidth="0.9" fill="none" strokeLinecap="round" opacity="0.55" />
      <ellipse cx="58" cy="34" rx="8" ry="6" fill="none" stroke={C.ink} strokeWidth="1.6" />
      <path d="M 64 34 L 74 35 L 64 37" stroke={C.rose} strokeWidth="1.6" fill="none" strokeLinejoin="round" />
      <circle cx="60" cy="33" r="1.6" fill={C.ink} />
      {/* 扇形尾 */}
      <path d="M 70 68 L 84 66" stroke={C.ink} strokeWidth="1.4" fill="none" strokeLinecap="round" />
      <path d="M 70 70 L 86 72" stroke={C.ink} strokeWidth="1.4" fill="none" strokeLinecap="round" />
      <path d="M 68 72 L 84 78" stroke={C.ink} strokeWidth="1.4" fill="none" strokeLinecap="round" />
      {/* 腿 + 绑信卷 */}
      <line x1="50" y1="74" x2="50" y2="86" stroke={C.rose} strokeWidth="1.4" strokeLinecap="round" />
      <line x1="58" y1="74" x2="58" y2="86" stroke={C.rose} strokeWidth="1.4" strokeLinecap="round" />
      <g transform="translate(46,82)">
        <rect x="0" y="0" width="16" height="4" rx="0.6" fill="none" stroke="#a67c52" strokeWidth="1" />
        <line x1="0" y1="2" x2="16" y2="2" stroke="#a67c52" strokeWidth="0.5" opacity="0.7" />
        <circle cx="8" cy="2" r="1.2" fill={C.rose} />
      </g>
    </svg>
  );
}

// ============================================================
// 10 · ShrikeArt v2 — 伯劳 · 质检员 / 审核员
// 特征: 黑眼罩 + 长尾 + 栖横枝 + 挂件
// ============================================================
export function ShrikeArtV2({ size = 100, className = "" }: BirdArtProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className={`${SVG_CLASS} ${className}`} aria-hidden>
      {/* 栖枝 */}
      <path d="M 8 70 Q 30 68,60 70 Q 80 72,92 70" stroke="#6b4e32" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      {/* 身 */}
      <path d="M 38 42 Q 52 40,60 46 Q 64 52,60 58 Q 52 64,42 62 Q 32 58,32 52 Q 32 44,38 42 Z" stroke={C.ink} strokeWidth="1.6" fill="none" strokeLinejoin="round" />
      {/* 长尾向下 */}
      <path d="M 60 58 Q 70 68,74 84" stroke={C.ink} strokeWidth="1.4" fill="none" strokeLinecap="round" />
      <path d="M 62 60 Q 74 70,78 86" stroke={C.ink} strokeWidth="1.2" fill="none" strokeLinecap="round" opacity="0.85" />
      {/* 黑眼罩 */}
      <path d="M 42 45 Q 50 43,58 45" stroke={C.inkDeep} strokeWidth="3.5" fill="none" strokeLinecap="round" />
      <circle cx="52" cy="45" r="1.2" fill={C.paper} />
      <circle cx="52" cy="45" r="0.6" fill={C.ink} />
      <path d="M 60 48 Q 68 48,70 50 Q 68 52,66 51" stroke={C.amber} strokeWidth="1.6" fill="none" strokeLinejoin="round" />
      {/* 爪抓枝 */}
      <line x1="44" y1="62" x2="44" y2="70" stroke="#6b4e32" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="52" y1="63" x2="52" y2="70" stroke="#6b4e32" strokeWidth="1.2" strokeLinecap="round" />
      {/* 伯劳特有:挂件签名 */}
      <path d="M 22 70 L 22 78" stroke={C.ink} strokeWidth="0.9" />
      <circle cx="22" cy="80" r="2.2" fill="none" stroke={C.rose} strokeWidth="1.1" />
    </svg>
  );
}

// ============================================================
// 映射表 · RoleKey → v2 组件
// 接口兼容 v1,任意使用 BIRD_ART 的地方可以换成 BIRD_ART_V2
// ============================================================
export const BIRD_ART_V2: Readonly<
  Record<RoleKey, React.FC<BirdArtProps>>
> = Object.freeze({
  "editor-in-chief": WoodpeckerArtV2,
  structure: WeaverArtV2,
  quality: OwlArtV2,
  ai_coding: RavenArtV2,
  data_quality: CormorantArtV2,
  "final-reviewer": GoshawkArtV2,
  "reader-feedback": DoveArtV2,
  "sample-reader": CuckooArtV2,
  archivist: KakapoArtV2,
  "qa-gatekeeper": ShrikeArtV2,
});
