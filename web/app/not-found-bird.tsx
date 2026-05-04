"use client";

import { useState } from "react";

/**
 * LostBird · 404 页的困惑啄木鸟
 *
 * 单独抽出来是为了让 not-found.tsx 保持 server component(便于 metadata
 * 静态预渲染),只把需要 onError 客户端逻辑的这一小块隔离到客户端。
 *
 * biz-lost.png 缺失时(图还没生成 / 部署落盘前),onError 触发 setHidden,
 * 整个 img 静默消失,not-found 页继续渲染文案 + CTA。
 */
export function LostBird() {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;

  return (
    <img
      src="/birds/biz-lost.png"
      alt=""
      aria-hidden
      width={220}
      height={220}
      style={{
        width: 220,
        height: 220,
        marginBottom: 16,
        opacity: 0.9,
        userSelect: "none",
      }}
      onError={() => setHidden(true)}
    />
  );
}
