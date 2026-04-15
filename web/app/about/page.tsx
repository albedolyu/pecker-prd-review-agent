/**
 * /about — 品牌故事 + 10 鸟彩蛋
 *
 * Server Component,不需要 client 依赖。内容从 lib/roles.ts 遍历渲染。
 *
 * 本页是整个产品**唯一**会同时出现"编辑部职能词"和"鸟名"的地方。其他所有
 * UI 文案只用职能词(主编/责编/审校/...),这里是 easter egg。
 *
 * Phase C.5 会用 Visual Storyteller agent 重写这一页的故事文案,把品牌形象
 * 讲得更有温度。当前是结构版。
 */

import Link from "next/link";
import { ArrowLeft, Sparkles } from "lucide-react";

import { ROLES, type RoleKey, type Role } from "@/lib/roles";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "关于啄木鸟 · 编辑部的 10 只鸟",
};

const CATEGORIES: ReadonlyArray<{
  title: string;
  hint: string;
  keys: ReadonlyArray<RoleKey>;
}> = [
  {
    title: "编辑部 · 上线评审",
    hint: "评审进行时,你会在报告里看到这六个名字。",
    keys: [
      "editor-in-chief",
      "structure",
      "quality",
      "ai_coding",
      "data_quality",
      "final-reviewer",
    ],
  },
  {
    title: "后台班组 · 看不见但一直在工作",
    hint: "他们藏在 CI、运维和反馈链路里,把日子过成日常。",
    keys: ["reader-feedback", "sample-reader", "archivist", "qa-gatekeeper"],
  },
] as const;

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-10 space-y-8">
      {/* ========== 标题 ========== */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5" />
          品牌彩蛋
        </div>
        <h1 className="text-3xl font-bold tracking-tight">
          啄木鸟编辑部 · 10 只鸟的故事
        </h1>
        <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
          啄木鸟(Pecker)是一个 10 个 agent 协作的 PRD 评审系统。
          我们偷懒地把它形容成&ldquo;PM 的编辑部&rdquo;——因为它真的就像一间编辑部:
          有人盯结构,有人盯逻辑,有人盯数据,
          还有人在你看不见的角落,默默把每一篇稿子的口径对齐。
        </p>
        <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
          代码里我们给每个 agent 起了鸟名,这是设计这套系统时的一点私心。
          但 UI 上它们都换上了&ldquo;主编 / 责编 / 审校&rdquo;这样的工牌,
          因为&ldquo;鸬鹚&rdquo;、&ldquo;鸮鹦&rdquo;、&ldquo;伯劳&rdquo;这几个字,
          确实不太适合出现在按钮上。这一页是唯一让两套名字并排站着的地方:
          鸟是它&ldquo;是什么&rdquo;,职能词是它&ldquo;在做什么&rdquo;。
        </p>
      </div>

      <Separator />

      {/* ========== 10 鸟分类卡片 ========== */}
      {CATEGORIES.map((cat) => (
        <section key={cat.title} className="space-y-4">
          <div>
            <h2 className="text-xl font-semibold">{cat.title}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{cat.hint}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {cat.keys.map((k) => (
              <BirdCard key={k} role={ROLES[k]} />
            ))}
          </div>
        </section>
      ))}

      <Separator />

      {/* ========== 返回 ========== */}
      <div className="flex justify-center pt-4">
        <Link
          href="/review"
          className={cn(buttonVariants({ variant: "outline" }))}
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          返回评审
        </Link>
      </div>
    </div>
  );
}

function BirdCard({ role }: { role: Role }) {
  const freqBadge =
    role.frequency === "high"
      ? { label: "高频", cls: "bg-primary/10 text-primary" }
      : role.frequency === "medium"
        ? { label: "中频", cls: "bg-amber-500/10 text-amber-700 dark:text-amber-400" }
        : role.frequency === "low"
          ? { label: "后台", cls: "bg-muted text-muted-foreground" }
          : { label: "隐藏", cls: "bg-muted text-muted-foreground" };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-baseline justify-between">
          <span className="flex items-baseline gap-2">
            <span className="text-2xl" role="img" aria-label={role.birdName}>
              {role.birdEmoji}
            </span>
            <span className="text-base font-semibold">{role.label}</span>
            <span className="text-xs font-normal text-muted-foreground">
              · 又名 {role.birdName}
            </span>
          </span>
          <Badge variant="secondary" className={freqBadge.cls}>
            {freqBadge.label}
          </Badge>
        </CardTitle>
        <CardDescription className="text-xs">{role.responsibility}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-xs leading-relaxed text-muted-foreground">
          {role.description}
        </p>
      </CardContent>
    </Card>
  );
}
