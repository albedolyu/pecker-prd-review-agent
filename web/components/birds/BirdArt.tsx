/**
 * BirdArt —— 10 只鸟的独特 SVG 形象
 *
 * 设计原则:
 * - 每只鸟都是手绘的独立 SVG 组件,不共用模板
 * - 统一 viewBox 80x80,stroke 手绘风格(linejoin round, linecap round)
 * - 每只鸟有独特的姿态、主色、辅色 + 1-2 个专属细节装饰
 *   (钩喙 / 眼罩 / 羽冠 / 尾翎 / 脚趾 / 挂虫 / 书本 等)
 * - 颜色贴近真实鸟种的自然色,而不是 tailwind 标准色
 * - pointer-events-none + select-none 避免再出现 emoji 白屏
 *
 * 和 RoleKey 的映射表在文件末尾 BIRD_ART 导出。
 *
 * 给 BirdCard / ForestLanding 使用:
 *   import { BIRD_ART } from "@/components/birds/BirdArt";
 *   const Art = BIRD_ART[role.key];
 *   <Art size={88} />
 */

import type { RoleKey } from "@/lib/roles";

interface BirdArtProps {
  size?: number;
  className?: string;
}

// 统一的 stroke 风格(用函数减少重复)
function strokeProps(color = "#1a1a1a", w = 1.7) {
  return {
    stroke: color,
    strokeWidth: w,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    fill: "none",
  };
}

// ============================================================
// 1. WoodpeckerArt —— 啄木鸟(主编)
// 红冠 + 黑白身 + 长橙喙 + 敲树姿态
// ============================================================
export function WoodpeckerArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 身子 —— 黑色椭圆偏斜 */}
      <ellipse cx="38" cy="46" rx="17" ry="14" fill="#1f2937" />
      {/* 白肚 */}
      <ellipse cx="36" cy="52" rx="10" ry="7" fill="#f5f4f1" />
      {/* 头 —— 黑色圆 */}
      <circle cx="48" cy="28" r="11" fill="#1f2937" />
      {/* 红冠 —— 头顶三撮羽毛 */}
      <path d="M 44 18 Q 47 12, 50 18" {...strokeProps("#dc2626", 2.2)} />
      <path d="M 47 17 L 48 10" {...strokeProps("#dc2626", 2.2)} />
      <path d="M 50 18 Q 53 13, 55 19" {...strokeProps("#dc2626", 2.2)} />
      {/* 眼 */}
      <circle cx="51" cy="27" r="1.6" fill="#f5f4f1" />
      <circle cx="51.2" cy="27.2" r="0.7" fill="#1f2937" />
      {/* 长橙喙 —— 左上方尖喙 */}
      <path d="M 58 30 L 72 26 L 58 32 Z" fill="#f59e0b" stroke="#92400e" strokeWidth="0.8" />
      {/* 翅膀纹理 —— 羽毛线 */}
      <path d="M 26 42 Q 30 46, 26 50" {...strokeProps("#0f172a", 1.2)} />
      <path d="M 22 44 Q 26 48, 22 52" {...strokeProps("#0f172a", 1.2)} />
      {/* 腿 + 脚 —— 抓在树枝上 */}
      <path d="M 35 59 L 33 68" {...strokeProps("#78350f", 2)} />
      <path d="M 43 59 L 45 68" {...strokeProps("#78350f", 2)} />
      <path d="M 30 68 L 50 68" {...strokeProps("#78350f", 1.5)} />
      {/* 树干暗示 —— 右侧小竖线 */}
      <path d="M 70 20 L 68 74" {...strokeProps("#92400e", 2.5)} />
      <path d="M 70 30 L 72 32" {...strokeProps("#92400e", 1)} />
      <path d="M 68 50 L 66 52" {...strokeProps("#92400e", 1)} />
    </svg>
  );
}

// ============================================================
// 2. WeaverArt —— 织布鸟(责编)
// 黄羽胖圆 + 黑眼罩 + 脚下一团乱线(象征结构)
// ============================================================
export function WeaverArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 身子 —— 鲜黄胖圆 */}
      <ellipse cx="40" cy="38" rx="20" ry="18" fill="#eab308" />
      {/* 黄身阴影 */}
      <path
        d="M 22 38 Q 25 52, 40 56 Q 55 52, 58 38"
        fill="#ca8a04"
        opacity="0.55"
      />
      {/* 黑色眼罩 —— 标志性的"weaver mask" */}
      <path
        d="M 26 28 Q 40 22, 54 28 L 54 36 Q 40 40, 26 36 Z"
        fill="#1f2937"
      />
      {/* 眼睛 */}
      <circle cx="33" cy="31" r="1.8" fill="#fde047" />
      <circle cx="47" cy="31" r="1.8" fill="#fde047" />
      {/* 小黑喙 */}
      <path
        d="M 40 36 L 38 42 L 42 42 Z"
        fill="#78350f"
      />
      {/* 翅羽纹 */}
      <path d="M 24 42 Q 28 48, 30 54" {...strokeProps("#78350f", 1.3)} />
      <path d="M 30 45 Q 34 50, 34 56" {...strokeProps("#78350f", 1.3)} />
      {/* 脚 */}
      <path d="M 36 56 L 34 64" {...strokeProps("#78350f", 2)} />
      <path d="M 44 56 L 46 64" {...strokeProps("#78350f", 2)} />
      {/* 脚下一团乱线 —— 织布鸟的招牌,象征"结构要织齐" */}
      <path
        d="M 22 68 Q 30 62, 40 70 Q 50 62, 58 68 Q 52 74, 40 72 Q 28 74, 22 68"
        {...strokeProps("#f97316", 1.3)}
      />
      <path d="M 28 68 L 52 72" {...strokeProps("#f97316", 1.1)} />
      <path d="M 32 74 Q 40 66, 48 74" {...strokeProps("#f97316", 1.1)} />
    </svg>
  );
}

// ============================================================
// 3. OwlArt —— 猫头鹰(审校)
// 巨大双眼 + 耳朵 + 灰棕羽 + 腹部羽斑
// ============================================================
export function OwlArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 身子 —— 灰棕椭圆 */}
      <ellipse cx="40" cy="44" rx="22" ry="26" fill="#78350f" />
      {/* 腹部浅色 */}
      <ellipse cx="40" cy="52" rx="15" ry="17" fill="#d6b894" />
      {/* 腹部羽毛纹(3 行小 v) */}
      <path d="M 32 48 L 35 51 L 38 48" {...strokeProps("#78350f", 1)} />
      <path d="M 42 48 L 45 51 L 48 48" {...strokeProps("#78350f", 1)} />
      <path d="M 34 56 L 37 59 L 40 56" {...strokeProps("#78350f", 1)} />
      <path d="M 40 56 L 43 59 L 46 56" {...strokeProps("#78350f", 1)} />
      {/* 耳朵 —— 两个小三角 */}
      <path d="M 22 24 L 24 14 L 30 22 Z" fill="#78350f" />
      <path d="M 58 24 L 56 14 L 50 22 Z" fill="#78350f" />
      {/* 脸盘 */}
      <ellipse cx="40" cy="34" rx="20" ry="16" fill="#a16207" />
      {/* 两只大圆眼 */}
      <circle cx="31" cy="34" r="8" fill="#f5f4f1" />
      <circle cx="49" cy="34" r="8" fill="#f5f4f1" />
      {/* 黄虹膜 */}
      <circle cx="31" cy="34" r="5.5" fill="#facc15" />
      <circle cx="49" cy="34" r="5.5" fill="#facc15" />
      {/* 黑瞳 */}
      <circle cx="31" cy="34" r="2.8" fill="#111827" />
      <circle cx="49" cy="34" r="2.8" fill="#111827" />
      {/* 瞳点亮 */}
      <circle cx="32.2" cy="32.8" r="0.8" fill="#f5f4f1" />
      <circle cx="50.2" cy="32.8" r="0.8" fill="#f5f4f1" />
      {/* 钩喙 */}
      <path d="M 38 42 L 40 48 L 42 42 Z" fill="#78350f" />
      {/* 脚 */}
      <path d="M 34 70 L 32 76" {...strokeProps("#78350f", 2)} />
      <path d="M 46 70 L 48 76" {...strokeProps("#78350f", 2)} />
    </svg>
  );
}

// ============================================================
// 4. RavenArt —— 渡鸦(技术编辑)
// 纯黑 + 尖喙 + 反光羽毛 + 脚下小齿轮/电路
// ============================================================
export function RavenArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 身子 —— 纯黑椭圆偏斜 */}
      <ellipse cx="36" cy="44" rx="20" ry="16" fill="#0c0a09" />
      {/* 紫光反射(羽毛光泽) */}
      <path
        d="M 22 40 Q 30 34, 40 36"
        {...strokeProps("#6d28d9", 1.5)}
      />
      <path
        d="M 26 50 Q 34 46, 42 50"
        {...strokeProps("#4c1d95", 1.3)}
      />
      {/* 头 */}
      <circle cx="50" cy="30" r="11" fill="#0c0a09" />
      {/* 眼 —— 锐利小金眼 */}
      <circle cx="53" cy="28" r="1.8" fill="#fde68a" />
      <circle cx="53.3" cy="28.3" r="0.8" fill="#0c0a09" />
      {/* 长尖喙 */}
      <path
        d="M 60 30 L 73 27 L 60 33 Z"
        fill="#0c0a09"
      />
      <path d="M 60 30 L 73 27" {...strokeProps("#4c1d95", 0.6)} />
      {/* 翅膀 —— 尖锐羽毛线 */}
      <path d="M 18 40 L 28 36" {...strokeProps("#27272a", 1.5)} />
      <path d="M 18 46 L 28 44" {...strokeProps("#27272a", 1.5)} />
      <path d="M 20 52 L 30 52" {...strokeProps("#27272a", 1.5)} />
      {/* 尾羽 —— 扇形 */}
      <path
        d="M 18 48 L 10 44 L 12 56 L 20 52 Z"
        fill="#0c0a09"
      />
      {/* 脚 */}
      <path d="M 32 60 L 30 70" {...strokeProps("#27272a", 2)} />
      <path d="M 40 60 L 42 70" {...strokeProps("#27272a", 2)} />
      {/* 脚下小齿轮 —— 技术编辑的身份标 */}
      <circle
        cx="58"
        cy="66"
        r="5"
        fill="none"
        stroke="#6d28d9"
        strokeWidth="1.3"
      />
      <circle cx="58" cy="66" r="1.5" fill="#6d28d9" />
      <path d="M 58 60 L 58 63" {...strokeProps("#6d28d9", 1.2)} />
      <path d="M 58 69 L 58 72" {...strokeProps("#6d28d9", 1.2)} />
      <path d="M 52 66 L 55 66" {...strokeProps("#6d28d9", 1.2)} />
      <path d="M 61 66 L 64 66" {...strokeProps("#6d28d9", 1.2)} />
    </svg>
  );
}

// ============================================================
// 5. CormorantArt —— 鸬鹚(数据核对员)
// 长颈 + 深墨蓝 + 水波纹 + 长直喙
// ============================================================
export function CormorantArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 水波纹 —— 底部 2 条 */}
      <path d="M 8 68 Q 20 64, 32 68 Q 44 72, 56 68 Q 68 64, 76 68" {...strokeProps("#06b6d4", 1.2)} />
      <path d="M 10 74 Q 22 70, 34 74 Q 46 78, 58 74 Q 70 70, 74 74" {...strokeProps("#0891b2", 1)} />
      {/* 身子 —— 深墨蓝椭圆 */}
      <ellipse cx="40" cy="52" rx="20" ry="12" fill="#134e4a" />
      {/* 腹部光泽 */}
      <ellipse cx="40" cy="55" rx="14" ry="6" fill="#0f766e" />
      {/* 长颈 —— 从身体向上弯 */}
      <path
        d="M 52 44 Q 56 28, 62 20"
        {...strokeProps("#134e4a", 9)}
      />
      <path
        d="M 52 44 Q 56 28, 62 20"
        {...strokeProps("#0f766e", 6)}
      />
      {/* 头 */}
      <circle cx="62" cy="18" r="6" fill="#134e4a" />
      {/* 长直喙 —— 尖锐水平喙 */}
      <path
        d="M 68 18 L 78 16 L 68 20 Z"
        fill="#f59e0b"
        stroke="#92400e"
        strokeWidth="0.6"
      />
      {/* 眼 —— 绿色 */}
      <circle cx="64" cy="16" r="1.4" fill="#86efac" />
      <circle cx="64.2" cy="16.2" r="0.6" fill="#134e4a" />
      {/* 翅膀 —— 侧面几道羽 */}
      <path d="M 22 48 L 34 46" {...strokeProps("#0a3635", 1.3)} />
      <path d="M 22 54 L 34 52" {...strokeProps("#0a3635", 1.3)} />
      <path d="M 22 60 L 34 58" {...strokeProps("#0a3635", 1.3)} />
      {/* 尾羽 */}
      <path d="M 20 58 L 12 56 L 16 64 Z" fill="#134e4a" />
      {/* 脚 —— 藏在水下的小三角 */}
      <path d="M 38 64 L 36 68 L 40 68 Z" fill="#92400e" />
      <path d="M 46 64 L 44 68 L 48 68 Z" fill="#92400e" />
    </svg>
  );
}

// ============================================================
// 6. GoshawkArt —— 苍鹰(终审)
// 钩喙 + 锐眼 + 展翅 + 棕白羽
// ============================================================
export function GoshawkArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 展翅 —— 左右两翼张开 */}
      <path
        d="M 14 40 Q 8 28, 20 24 Q 30 26, 36 34 L 36 48 Q 22 52, 14 40 Z"
        fill="#451a03"
      />
      <path
        d="M 66 40 Q 72 28, 60 24 Q 50 26, 44 34 L 44 48 Q 58 52, 66 40 Z"
        fill="#451a03"
      />
      {/* 翅膀羽尖纹 */}
      <path d="M 14 34 L 18 32" {...strokeProps("#78350f", 1.2)} />
      <path d="M 12 40 L 16 40" {...strokeProps("#78350f", 1.2)} />
      <path d="M 14 46 L 18 46" {...strokeProps("#78350f", 1.2)} />
      <path d="M 66 34 L 62 32" {...strokeProps("#78350f", 1.2)} />
      <path d="M 68 40 L 64 40" {...strokeProps("#78350f", 1.2)} />
      <path d="M 66 46 L 62 46" {...strokeProps("#78350f", 1.2)} />
      {/* 身子 —— 深棕 */}
      <ellipse cx="40" cy="46" rx="11" ry="16" fill="#78350f" />
      {/* 腹部米白条纹 */}
      <ellipse cx="40" cy="52" rx="7" ry="10" fill="#f5f4f1" />
      <path d="M 34 48 L 46 48" {...strokeProps("#78350f", 0.9)} />
      <path d="M 34 53 L 46 53" {...strokeProps("#78350f", 0.9)} />
      <path d="M 34 58 L 46 58" {...strokeProps("#78350f", 0.9)} />
      {/* 头 */}
      <circle cx="40" cy="26" r="10" fill="#451a03" />
      {/* 头顶米白 */}
      <path
        d="M 32 20 Q 40 16, 48 20 L 48 26 Q 40 22, 32 26 Z"
        fill="#f5f4f1"
      />
      {/* 锐利金眼 */}
      <circle cx="36" cy="26" r="2" fill="#facc15" />
      <circle cx="36" cy="26" r="1" fill="#111827" />
      <path d="M 34 25 L 38 25" {...strokeProps("#78350f", 0.8)} />
      {/* 钩喙 —— 弯曲下勾 */}
      <path
        d="M 44 28 Q 50 30, 48 34 Q 44 33, 44 30"
        fill="#facc15"
        stroke="#78350f"
        strokeWidth="0.8"
      />
      {/* 脚 + 爪 */}
      <path d="M 36 62 L 34 72" {...strokeProps("#facc15", 2)} />
      <path d="M 44 62 L 46 72" {...strokeProps("#facc15", 2)} />
      <path d="M 34 72 L 30 74" {...strokeProps("#78350f", 1.2)} />
      <path d="M 34 72 L 36 76" {...strokeProps("#78350f", 1.2)} />
      <path d="M 46 72 L 50 74" {...strokeProps("#78350f", 1.2)} />
      <path d="M 46 72 L 44 76" {...strokeProps("#78350f", 1.2)} />
    </svg>
  );
}

// ============================================================
// 7. DoveArt —— 信鸽(读者反馈员)
// 白灰胖 + 叼一片叶子 + 小红眼
// ============================================================
export function DoveArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 身子 —— 白灰圆胖 */}
      <ellipse cx="40" cy="46" rx="22" ry="18" fill="#e5e7eb" />
      {/* 背部阴影 */}
      <path
        d="M 20 42 Q 30 30, 40 30 Q 50 30, 60 42 L 60 48 Q 40 38, 20 48 Z"
        fill="#9ca3af"
      />
      {/* 头 */}
      <circle cx="56" cy="30" r="9" fill="#f3f4f6" />
      {/* 后颈阴影 */}
      <path
        d="M 50 26 Q 56 20, 62 24"
        {...strokeProps("#6b7280", 2)}
      />
      {/* 红眼 */}
      <circle cx="58" cy="28" r="1.6" fill="#b91c1c" />
      <circle cx="58.3" cy="27.8" r="0.6" fill="#f3f4f6" />
      {/* 粉色小喙 */}
      <path d="M 62 30 L 70 30 L 62 33 Z" fill="#f472b6" />
      {/* 一片叶子 —— 嘴里叼着,象征读者反馈 */}
      <ellipse
        cx="74"
        cy="31"
        rx="5"
        ry="2.5"
        fill="#16a34a"
        transform="rotate(15 74 31)"
      />
      <path
        d="M 70 32 L 78 30"
        {...strokeProps("#15803d", 0.8)}
      />
      {/* 翅膀分线 */}
      <path d="M 22 46 L 40 52" {...strokeProps("#6b7280", 1.4)} />
      <path d="M 22 52 L 38 56" {...strokeProps("#6b7280", 1.4)} />
      <path d="M 22 58 L 36 60" {...strokeProps("#6b7280", 1.4)} />
      {/* 尾羽 */}
      <path
        d="M 18 48 L 8 46 L 10 58 L 20 56 Z"
        fill="#9ca3af"
      />
      {/* 脚 */}
      <path d="M 36 64 L 34 72" {...strokeProps("#f472b6", 2)} />
      <path d="M 46 64 L 48 72" {...strokeProps("#f472b6", 2)} />
    </svg>
  );
}

// ============================================================
// 8. CuckooArt —— 杜鹃(试读员)
// 灰羽 + 白腹斑点 + 长尾 + 歪头问号
// ============================================================
export function CuckooArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 长尾 —— 向右下方,是杜鹃的特点 */}
      <path
        d="M 52 50 L 74 66 L 72 60 L 56 46 Z"
        fill="#6b7280"
      />
      <path d="M 58 50 L 70 62" {...strokeProps("#4b5563", 1)} />
      <path d="M 60 54 L 72 64" {...strokeProps("#4b5563", 1)} />
      {/* 身子 —— 灰椭圆 */}
      <ellipse cx="36" cy="44" rx="18" ry="15" fill="#6b7280" />
      {/* 腹部白色 */}
      <ellipse cx="34" cy="50" rx="11" ry="8" fill="#f3f4f6" />
      {/* 腹部斑点 —— 杜鹃的经典花纹 */}
      <circle cx="30" cy="48" r="1" fill="#4b5563" />
      <circle cx="34" cy="52" r="1" fill="#4b5563" />
      <circle cx="38" cy="48" r="1" fill="#4b5563" />
      <circle cx="32" cy="55" r="1" fill="#4b5563" />
      <circle cx="36" cy="56" r="1" fill="#4b5563" />
      {/* 头 —— 歪头姿态,略倾斜 */}
      <circle cx="26" cy="28" r="10" fill="#6b7280" />
      {/* 小冠 —— 头顶一撮 */}
      <path d="M 22 18 L 24 13" {...strokeProps("#374151", 1.5)} />
      <path d="M 26 17 L 26 12" {...strokeProps("#374151", 1.5)} />
      <path d="M 30 18 L 28 13" {...strokeProps("#374151", 1.5)} />
      {/* 眼 —— 斜眼带红腮 */}
      <circle cx="24" cy="28" r="1.8" fill="#fcd34d" />
      <circle cx="24" cy="28" r="0.9" fill="#1f2937" />
      {/* 粉红腮 */}
      <ellipse cx="22" cy="32" rx="2" ry="1" fill="#f472b6" opacity="0.7" />
      {/* 小喙 —— 向左下 */}
      <path d="M 18 30 L 13 32 L 18 32 Z" fill="#1f2937" />
      {/* 问号 —— 旁边浮一个小 ? 象征"这条站得住吗" */}
      <text
        x="8"
        y="18"
        fontSize="10"
        fill="#dc2626"
        fontFamily="serif"
        fontStyle="italic"
      >
        ?
      </text>
      {/* 脚 */}
      <path d="M 32 58 L 30 66" {...strokeProps("#1f2937", 1.8)} />
      <path d="M 40 58 L 42 66" {...strokeProps("#1f2937", 1.8)} />
    </svg>
  );
}

// ============================================================
// 9. KakapoArt —— 鸮鹦(资料员)
// 绿胖 + 大脚不会飞 + 眯眼 + 头顶小书本
// ============================================================
export function KakapoArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 身子 —— 鲜绿大圆 */}
      <ellipse cx="40" cy="48" rx="24" ry="20" fill="#15803d" />
      {/* 腹部浅绿 */}
      <ellipse cx="40" cy="54" rx="16" ry="12" fill="#86efac" />
      {/* 羽毛纹理 */}
      <path d="M 22 44 Q 28 50, 26 56" {...strokeProps("#14532d", 1)} />
      <path d="M 18 48 Q 24 54, 22 60" {...strokeProps("#14532d", 1)} />
      <path d="M 58 44 Q 52 50, 54 56" {...strokeProps("#14532d", 1)} />
      <path d="M 62 48 Q 56 54, 58 60" {...strokeProps("#14532d", 1)} />
      {/* 头 —— 稍圆 */}
      <ellipse cx="40" cy="30" rx="15" ry="13" fill="#15803d" />
      {/* 脸盘 —— 类似猫头鹰的盘面 */}
      <ellipse cx="40" cy="34" rx="12" ry="9" fill="#22c55e" />
      {/* 眯眼 —— 两条短弧线(睡相) */}
      <path
        d="M 32 34 Q 35 36, 38 34"
        {...strokeProps("#14532d", 1.8)}
      />
      <path
        d="M 42 34 Q 45 36, 48 34"
        {...strokeProps("#14532d", 1.8)}
      />
      {/* 黄喙 */}
      <path
        d="M 38 40 Q 40 44, 42 40 L 41 38 L 39 38 Z"
        fill="#facc15"
        stroke="#ca8a04"
        strokeWidth="0.5"
      />
      {/* 头顶小书本 —— 资料员的身份标 */}
      <rect x="34" y="12" width="12" height="8" fill="#fef3c7" stroke="#92400e" strokeWidth="0.8" />
      <path d="M 40 12 L 40 20" {...strokeProps("#92400e", 0.8)} />
      <path d="M 36 14 L 38 14" {...strokeProps("#92400e", 0.5)} />
      <path d="M 36 16 L 38 16" {...strokeProps("#92400e", 0.5)} />
      <path d="M 42 14 L 44 14" {...strokeProps("#92400e", 0.5)} />
      <path d="M 42 16 L 44 16" {...strokeProps("#92400e", 0.5)} />
      {/* 大脚 —— 不会飞,站得很稳,特别大的脚 */}
      <ellipse cx="30" cy="72" rx="6" ry="3" fill="#92400e" />
      <ellipse cx="50" cy="72" rx="6" ry="3" fill="#92400e" />
      <path d="M 34 60 L 30 72" {...strokeProps("#15803d", 2.2)} />
      <path d="M 46 60 L 50 72" {...strokeProps("#15803d", 2.2)} />
      {/* 脚趾线 */}
      <path d="M 26 72 L 24 74" {...strokeProps("#78350f", 1)} />
      <path d="M 34 72 L 36 74" {...strokeProps("#78350f", 1)} />
      <path d="M 46 72 L 44 74" {...strokeProps("#78350f", 1)} />
      <path d="M 54 72 L 56 74" {...strokeProps("#78350f", 1)} />
    </svg>
  );
}

// ============================================================
// 10. ShrikeArt —— 伯劳(质检员)
// 黑眼罩 + 钩喙 + 灰白羽 + 挂一个小钩(伯劳挂虫)
// ============================================================
export function ShrikeArt({ size = 80, className = "" }: BirdArtProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {/* 树枝 —— 水平横着,伯劳站在上面 */}
      <path d="M 8 62 L 72 62" {...strokeProps("#78350f", 2.5)} />
      <path d="M 16 60 L 14 58" {...strokeProps("#78350f", 1)} />
      <path d="M 60 60 L 62 58" {...strokeProps("#78350f", 1)} />
      {/* 挂钩 —— 树枝上挂一个"战利品"象征,伯劳的招牌 */}
      <path
        d="M 66 62 L 66 70 Q 66 74, 70 74"
        {...strokeProps("#9ca3af", 1.3)}
      />
      {/* 挂的小东西 —— 一只虫 */}
      <ellipse cx="70" cy="74" rx="3" ry="1.5" fill="#dc2626" opacity="0.75" />
      <path d="M 68 74 L 72 74" {...strokeProps("#7f1d1d", 0.6)} />
      {/* 身子 —— 灰白椭圆 */}
      <ellipse cx="36" cy="48" rx="17" ry="13" fill="#e5e7eb" />
      {/* 背部深灰 */}
      <path
        d="M 20 44 Q 28 36, 36 36 Q 44 36, 52 44 L 52 48 Q 36 42, 20 48 Z"
        fill="#6b7280"
      />
      {/* 头 */}
      <circle cx="46" cy="32" r="10" fill="#e5e7eb" />
      {/* 头顶深灰 */}
      <path
        d="M 38 28 Q 46 22, 54 28"
        {...strokeProps("#4b5563", 4)}
      />
      {/* 黑色眼罩 —— 伯劳标志,横贯整个眼 */}
      <path
        d="M 38 32 L 54 32 L 54 36 L 38 36 Z"
        fill="#111827"
      />
      {/* 眼 —— 黑罩里露一点红 */}
      <circle cx="47" cy="34" r="1" fill="#dc2626" />
      {/* 钩喙 —— 弯钩状,小型猛禽特征 */}
      <path
        d="M 54 36 Q 60 36, 58 40 Q 55 39, 55 37"
        fill="#111827"
      />
      {/* 翅羽纹 */}
      <path d="M 22 48 L 32 46" {...strokeProps("#374151", 1.3)} />
      <path d="M 22 52 L 30 52" {...strokeProps("#374151", 1.3)} />
      {/* 尾羽 —— 尖尾 */}
      <path
        d="M 18 48 L 8 50 L 10 56 L 20 54 Z"
        fill="#4b5563"
      />
      {/* 脚 —— 抓树枝 */}
      <path d="M 32 60 L 32 62" {...strokeProps("#92400e", 2)} />
      <path d="M 40 60 L 40 62" {...strokeProps("#92400e", 2)} />
    </svg>
  );
}

// ============================================================
// 映射表:RoleKey → 对应的 BirdArt 组件
// ============================================================
export const BIRD_ART: Readonly<
  Record<RoleKey, React.FC<BirdArtProps>>
> = Object.freeze({
  "editor-in-chief": WoodpeckerArt,
  structure: WeaverArt,
  quality: OwlArt,
  ai_coding: RavenArt,
  data_quality: CormorantArt,
  "final-reviewer": GoshawkArt,
  "reader-feedback": DoveArt,
  "sample-reader": CuckooArt,
  archivist: KakapoArt,
  "qa-gatekeeper": ShrikeArt,
});
