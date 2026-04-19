/**
 * /system/* layout · 让 Next.js 16 app router 把 /system 识别为 valid segment
 *
 * 没这个 layout · 只有 /system/health/ 和 /system/prompts/ 子目录,
 * Turbopack 的 lazy route discovery 不会扫到它们,子路由一律 404。
 *
 * 不加样式 · 只做透传 · 子路由自己管外观。
 */

export default function SystemLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
