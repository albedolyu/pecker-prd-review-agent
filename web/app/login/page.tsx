/**
 * /login — 团队共享密码 + reviewer 名字
 *
 * 这里是 server component,用于把 client LoginForm 包在 Suspense 边界里。
 * useSearchParams() 在 client 组件里需要 Suspense 包围才能静态预渲染。
 *
 * 真正的登录表单在 ./LoginForm.tsx。
 */

import { Suspense } from "react";
import { LoginForm } from "./LoginForm";

export const metadata = {
  title: "啄木鸟登录",
};

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center text-sm text-muted-foreground">
          加载...
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
