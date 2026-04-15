import { redirect } from "next/navigation";

/**
 * 首页 — 简单重定向到评审 wizard。
 *
 * 未来如果需要 landing page,在这里加欢迎内容 + 去 /review 的 CTA。
 * 当前保持最小,用户打开根路径直接进主流程。
 */
export default function Home() {
  redirect("/review");
}
