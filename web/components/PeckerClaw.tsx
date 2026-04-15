/**
 * PeckerClaw — 啄木鸟爪印 SVG
 *
 * 用作 section divider / 页脚签名 / 装饰,取代通用的"一道横线"。
 * 3 个爪趾 + 后跟,inline stroke 线条,极小尺寸(~18px)。
 *
 * 使用约定: 一般 3 个连用,每个带不同的 translate + opacity,
 * 让它像"真的走过"的轻微不齐。见 /about 页的使用。
 */

interface PeckerClawProps {
  className?: string;
}

export function PeckerClaw({ className = "" }: PeckerClawProps) {
  return (
    <svg
      width="18"
      height="20"
      viewBox="0 0 18 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      className={className}
      aria-hidden
    >
      {/* 3 个爪趾 */}
      <path d="M9 2 L9 12" />
      <path d="M3.5 5 L8 11" />
      <path d="M14.5 5 L10 11" />
      {/* 后跟 */}
      <path d="M9 12 Q 9 15, 7.5 17.2" />
      {/* 关节点 */}
      <circle cx="9" cy="12" r="0.9" fill="currentColor" />
      {/* 压痕小点 */}
      <circle cx="3.3" cy="5.1" r="0.45" fill="currentColor" opacity="0.7" />
      <circle cx="14.7" cy="5.1" r="0.45" fill="currentColor" opacity="0.7" />
      <circle cx="9.1" cy="1.9" r="0.45" fill="currentColor" opacity="0.7" />
    </svg>
  );
}

/**
 * 三爪印分隔线组 —— 用在 section divider 处,取代普通 <hr>。
 * 三个爪印不等距 + 不等透明度 + 轻微 translate,像真的走过。
 */
export function PeckerClawDivider({
  className = "",
}: {
  className?: string;
}) {
  return (
    <div
      className={`flex items-center gap-3 text-foreground/30 ${className}`}
      aria-hidden
    >
      <span className="h-px flex-1 bg-current" />
      <PeckerClaw className="opacity-55" />
      <PeckerClaw className="-translate-x-[2px] translate-y-[1px] opacity-70" />
      <PeckerClaw className="-translate-x-[4px] -translate-y-[3px] opacity-85" />
      <span className="h-px flex-1 bg-current" />
    </div>
  );
}
