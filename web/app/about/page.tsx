/**
 * /about — 品牌故事 + 10 鸟家族
 *
 * 整个产品唯一同时出现"职能词 + 鸟名"的地方。承载:
 * - 起源故事(Visual Storyteller 块 1)
 * - 10 鸟名册(不规则 grid,BirdCard 工作证风)
 * - 编辑部日常小插曲(Visual Storyteller 块 2)
 * - colophon 版权页(Visual Storyteller 块 3)
 *
 * 视觉(UI Designer 去 AI 味方案):
 * - 刊头:第壹期 / 卷一 / 编辑部名册 / MMXXVI 春
 * - 大标题带 drop cap "啄" 用 pecker-red
 * - 右上角手写"存档"章
 * - 右栏错位引语块 + 美纹胶带
 * - 卡片 12-col 不规则栏位,故意错位 + tilt
 * - PeckerClawDivider 取代普通分隔线
 */

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { ROLES, type RoleKey, type Role } from "@/lib/roles";
import { buttonVariants } from "@/components/ui/button";
import { PeckerClawDivider } from "@/components/PeckerClaw";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "关于啄木鸟 · 编辑部的 10 只鸟",
};

// 前台 6 位 + 后台 4 位,决定 12 栏位权重
interface CategoryDef {
  title: string;
  orderMark: string;
  meta: string;
  keys: ReadonlyArray<RoleKey>;
  /** 12-col 栏位权重,和 keys 一一对应 */
  spans: ReadonlyArray<number>;
  /** 垂直错位(mt-X),和 keys 一一对应,用于破网格 */
  offsets: ReadonlyArray<string>;
}

const CATEGORIES: ReadonlyArray<CategoryDef> = [
  {
    title: "编辑部 · 上线评审",
    orderMark: "栏目 壹",
    meta: "出勤 6 位 / 每期",
    keys: [
      "editor-in-chief",
      "structure",
      "quality",
      "ai_coding",
      "data_quality",
      "final-reviewer",
    ],
    spans: [7, 5, 5, 7, 6, 6],
    offsets: ["", "md:mt-6", "", "md:-mt-3", "md:mt-4", ""],
  },
  {
    title: "后台班组 · 看不见但一直在工作",
    orderMark: "栏目 贰",
    meta: "隐身 4 位 / 常年",
    keys: ["reader-feedback", "sample-reader", "archivist", "qa-gatekeeper"],
    spans: [6, 6, 7, 5],
    offsets: ["", "md:mt-5", "", "md:mt-3"],
  },
];

// 编辑部日常小插曲(Visual Storyteller 块 2)
const VIGNETTES: ReadonlyArray<{ title: string; body: string }> = [
  {
    title: "织布鸟和渡鸦又在为章节吵架",
    body: "织布鸟坚持这份稿子应该拆成五块,每块一个独立的功能点;渡鸦冷冷地说它用工具翻过了这份稿子的每一个角落,里面其实只有三件事值得拆,其他都是重复。这场架通常持续不到十分钟就会结束,因为它们都知道谁会被主编最后采纳 —— 取决于今天拆的是什么稿。",
  },
  {
    title: "猫头鹰和鸬鹚为一个字段的类型吵过三次",
    body: "第一次猫头鹰说&ldquo;这里写的是字符串&rdquo;,鸬鹚潜下去捞了一圈回来说&ldquo;里面存的是整数&rdquo;;第二次反过来;第三次两只鸟一起沉默了很久,然后同时看向了资料室的门 —— 鸮鹦那边一定有答案,只是它从不主动说。",
  },
  {
    title: "苍鹰每次出场都只有一句话",
    body: "它会在会议最后十分钟飞进来,在头顶盘旋两圈,停在窗台上沉默大概七秒,然后说&ldquo;这条我不同意&rdquo;。没有人敢问它是哪一条,因为它从不重审任何人已经说过的话,它只交叉看六个人一起说过的话,然后挑出那唯一一处自相矛盾的地方。",
  },
  {
    title: "信鸽是全编辑部最能跑的",
    body: "凌晨三点其他鸟都睡了,只有它还在路上,背着读者改稿的票据往回飞。它每次回来都很累,但它从不把所有票据一次性倒出来 —— 它会一点一点地把新的声音掺进老的规则里,像往一锅慢汤里续水,怕一次加太多把味道冲淡了。",
  },
  {
    title: "伯劳最讨厌一句话",
    body: "是&ldquo;再提交一次就好了&rdquo;。它挂刀的习惯是从山林里带来的,在它那张小桌子上,钩子上永远挂着几样被拦下来的东西:一串密钥、半段内网地址、一个没清掉的临时文件。它从不说教,只把这些东西挂给下一个路过的编辑看。",
  },
  {
    title: "鸮鹦是整栋楼里最博学的一位",
    body: "但它从不主动开口。它不会飞,走路也慢,大部分时间就蹲在地下室的资料堆里。只有当有鸟专程下楼来问它&ldquo;我们上次是怎么定义这个词的&rdquo;时,它才会慢吞吞地抬起头,指一指某一本某一页 —— 指得分毫不差。",
  },
];

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-[68rem] px-6 py-10 sm:px-10 sm:py-14">
      {/* ================== 刊头 ================== */}
      <header className="relative pb-6">
        <div className="flex items-baseline gap-3 font-mono text-[10px] uppercase tracking-[0.18em] text-foreground/55">
          <span className="whitespace-nowrap">第 壹 期</span>
          <span className="h-px flex-1 bg-foreground/70" />
          <span>卷一 · 编辑部名册</span>
          <span className="h-px flex-1 bg-foreground/70" />
          <span>MMXXVI 年 春</span>
        </div>
        <div className="mt-1 h-[2px] bg-foreground/70" />
        <div className="mt-[3px] h-px bg-foreground/40" />

        {/* 大标题 + drop cap "啄"红笔色 */}
        <h1 className="mt-10 font-serif text-[clamp(2.25rem,5vw,3.75rem)] leading-[0.96] tracking-tight text-foreground">
          <span
            className="float-left mr-3 mt-[0.12em] font-serif text-[5.5rem] leading-[0.78] text-pecker-red"
            aria-hidden
          >
            啄
          </span>
          <span className="sr-only">啄</span>木鸟编辑部
          <span className="mt-2 block font-sans text-[1.1rem] font-normal italic tracking-wide text-foreground/55">
            —— 十只鸟的故事,一份每天出刊的内部评审笔记
          </span>
        </h1>

        {/* 右上角"存档"章 —— 手写虚线红框 */}
        <div className="tilt-b absolute right-2 top-16 rounded-[2px] border border-dashed border-pecker-red/70 px-2 py-[3px] font-mono text-[10px] leading-tight text-pecker-red/85">
          存档 · 内部传阅
          <br />
          NO. 001 / 2026
        </div>
      </header>

      {/* ================== 起源故事(双栏,左正文 + 右引语) ================== */}
      <section className="mt-10 grid gap-[var(--spacing-gutter)] md:grid-cols-[1fr_0.58fr] md:items-start">
        {/* 左栏 —— 起源故事,首段 drop cap */}
        <article className="[text-align:justify] [hanging-punctuation:first_last] space-y-5 text-[15px] leading-[1.8] text-foreground/85">
          <p className="first-letter:float-left first-letter:mr-2 first-letter:pt-[0.1em] first-letter:font-serif first-letter:text-[3.6rem] first-letter:leading-[0.82] first-letter:text-foreground">
            那是一个很普通的周二下午。啄木鸟在一棵桦树上敲到第二百下的时候,突然意识到一件事 —— 它这辈子只做一件事,而且一直做对,不是因为它格外聪明,而是因为它每敲一下,树的回声都会告诉它下一下该敲哪里。一只鸟加无数次回声,比一百只鸟凭直觉乱啄要可靠得多。
          </p>
          <p>它决定办一本内部刊物。</p>
          <p>
            织布鸟是第一个答应的。它正因为一份结构散掉的稿子生闷气,听说有人要讲章节秩序,立刻背着自己那台老式织机来了。猫头鹰是被一句&ldquo;夜里你看得比谁都清&rdquo;劝来的,它没说话,只是把停栖的位置挪到了办公室最暗的角落。渡鸦本来不屑于加入任何组织,直到啄木鸟递给它一套工具箱,说&ldquo;这些都归你管,其他人碰不得&rdquo;,它才勉强点头。鸬鹚和苍鹰是一起来的 —— 一个负责下水,一个负责在高处看大局,它们二十年前就是搭档。
          </p>
          <p>
            前台六位凑齐了,但啄木鸟知道还不够。它花了更长的时间去找后台。信鸽是从很远的南方飞回来的,带着一沓读者的改稿单;鸮鹦走了三天三夜,慢悠悠地抱着整座资料室挪进了地下室;杜鹃谁都不喜欢,但啄木鸟坚持要给它留一张桌子;伯劳最后一个到,它沉默地把刀挂在了大门口的墙上。
          </p>
          <p>
            前台出稿,后台养稿。前台的六位每天会在评审会上碰面,吵架、推翻、定稿;后台的四位从不上会,却在每一期刊物的缝隙里留下痕迹。
            <span className="ink-mark">缺了前台,刊物出不来;缺了后台,刊物出得来,但会越办越差。</span>
          </p>
          <p className="text-foreground/70">
            如果你翻开这本工具的第一期,你会先看到六只鸟围坐的那张长桌;但你不会立刻看到另外四只 —— 它们在墙的后面,一直都在。
          </p>
        </article>

        {/* 右栏 —— 引语块(故意错位 + tilt + 美纹胶带) */}
        <aside className="nudge-out-r tilt-a relative mt-6 bg-pecker-kraft px-5 pb-5 pt-7 shadow-print">
          {/* 顶端美纹胶带 */}
          <span
            className="absolute -top-2 left-6 h-4 w-16 -rotate-2 bg-pecker-tape shadow-[0_1px_2px_rgba(0,0,0,0.08)]"
            aria-hidden
          />
          <div className="font-serif text-[1.35rem] leading-[1.35] text-foreground/88 before:mr-[0.1em] before:align-[-0.4em] before:font-serif before:text-[2.2rem] before:leading-[0] before:text-pecker-red/70 before:content-['\201C']">
            评审不是挑刺,是把没说清楚的事逼出来。
          </div>
          <div className="mt-3 font-mono text-[10px] uppercase tracking-[0.16em] text-foreground/50">
            —— 苍鹰,于某次终审会议
          </div>
        </aside>
      </section>

      {/* ================== 分隔:三爪印 ================== */}
      <PeckerClawDivider className="my-14" />

      {/* ================== 10 鸟名册 ================== */}
      {CATEGORIES.map((cat) => (
        <section key={cat.title} className="mb-14">
          {/* 栏目眉:编号 + 标题 + 出勤 meta */}
          <div className="mb-6 flex items-end justify-between">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-pecker-red/90">
                {cat.orderMark}
              </div>
              <h2 className="mt-[2px] font-serif text-[1.75rem] leading-tight tracking-tight">
                {cat.title}
              </h2>
            </div>
            <div className="pb-1 font-mono text-[10px] uppercase tracking-wide text-foreground/45">
              {cat.meta}
            </div>
          </div>

          {/* 不规则 12 列网格 */}
          <div className="grid auto-rows-min grid-cols-12 gap-[var(--spacing-col)]">
            {cat.keys.map((key, idx) => (
              <BirdCard
                key={key}
                role={ROLES[key]}
                index={idx + 1}
                className={cn(
                  `col-span-12 md:col-span-${cat.spans[idx]}`,
                  cat.offsets[idx] ?? "",
                )}
              />
            ))}
          </div>
        </section>
      ))}

      {/* ================== 分隔 ================== */}
      <PeckerClawDivider className="my-14" />

      {/* ================== 编辑部日常小插曲 ================== */}
      <section className="mb-14">
        <div className="mb-6">
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-pecker-red/90">
            栏目 叁
          </div>
          <h2 className="mt-[2px] font-serif text-[1.75rem] leading-tight tracking-tight">
            编辑部日常 · 小插曲
          </h2>
          <p className="mt-2 max-w-[58ch] text-[13px] leading-relaxed text-foreground/60">
            长期共事才有的那种默契和小摩擦。以下都是真事(大概)。
          </p>
        </div>

        <div className="grid grid-cols-1 gap-[var(--spacing-col)] md:grid-cols-2">
          {VIGNETTES.map((v, i) => (
            <div
              key={v.title}
              className={cn(
                "relative bg-pecker-kraft px-5 py-4 shadow-print",
                i % 3 === 0 && "tilt-c",
                i % 3 === 2 && "tilt-a",
              )}
            >
              <h3 className="font-serif text-[1.05rem] font-medium leading-snug tracking-tight text-foreground">
                {v.title}
              </h3>
              <p
                className="mt-2 text-[12.5px] leading-[1.72] text-foreground/75"
                dangerouslySetInnerHTML={{ __html: v.body }}
              />
              <span
                className="absolute right-3 top-3 font-mono text-[9px] uppercase tracking-wider text-foreground/35"
                aria-hidden
              >
                № {String(i + 1).padStart(2, "0")}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* ================== Colophon ================== */}
      <section className="mt-16 border-t-[3px] border-foreground/80 pt-6">
        <div className="mt-[3px] h-px bg-foreground/35" />
        <div className="mt-6 grid gap-6 md:grid-cols-[1fr_auto]">
          <p className="max-w-[62ch] text-[12.5px] leading-[1.8] text-foreground/65">
            本刊正文以 Fraunces 与苹方(PingFang SC)双字体排印,由主编啄木鸟亲自挑选 ——
            它说前者像一根敲得准的喙,后者像一张看得清的纸。刊物自 Phase A 起发行,
            现行至 Phase E,每一期编辑部都会少掉一些毛病,多出一点自知之明。
            如有脱漏、错字或冒犯之处,请往森林里写信,信鸽会带回来的。
          </p>
          <Link
            href="/review"
            className={cn(
              buttonVariants({ variant: "outline", size: "sm" }),
              "self-start",
            )}
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" />
            返回评审
          </Link>
        </div>
      </section>
    </div>
  );
}

// ============================================================
// BirdCard —— 工作证 / 出勤卡风格
// ============================================================

interface BirdCardProps {
  role: Role;
  index: number;
  className?: string;
}

function BirdCard({ role, index, className = "" }: BirdCardProps) {
  const freqMeta =
    role.frequency === "high"
      ? "高频"
      : role.frequency === "medium"
        ? "中频"
        : role.frequency === "low"
          ? "后台"
          : "隐藏";

  return (
    <article
      className={cn(
        "group relative bg-pecker-kraft pl-[var(--spacing-gutter)] pr-5 pt-[1.05rem] pb-[1.15rem] shadow-print transition-shadow duration-500 hover:shadow-print-lift",
        "before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-foreground",
        className,
      )}
    >
      {/* 左上角打孔 */}
      <span
        className="absolute left-[9px] top-[9px] h-[7px] w-[7px] rounded-full bg-background shadow-[inset_0_0_0_1px_oklch(0.18_0.008_60/0.5)]"
        aria-hidden
      />

      {/* 左侧纵向编号 */}
      <span
        className="absolute bottom-2 left-[6px] rotate-180 font-mono text-[9px] tracking-[0.22em] text-foreground/40"
        style={{ writingMode: "vertical-rl" }}
        aria-hidden
      >
        NO · {String(index).padStart(2, "0")}
      </span>

      {/* 顶行:职能 + 又名 + 频率 pill */}
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[10px] uppercase tracking-wider text-foreground/55">
            {role.key}
          </div>
          <h3 className="mt-[1px] font-serif text-[1.3rem] leading-[1.15] tracking-tight">
            {role.label}
            <span className="ml-2 text-[0.72em] font-light italic text-foreground/50">
              又名 {role.birdName}
            </span>
          </h3>
        </div>
        <span className="tilt-a shrink-0 rounded-[2px] border border-dashed border-pecker-red/55 px-[6px] py-[2px] font-mono text-[9px] uppercase tracking-wide text-pecker-red/90">
          {freqMeta}
        </span>
      </div>

      {/* 描述正文 */}
      <p
        className="mt-2 text-[12.5px] leading-[1.72] text-foreground/78"
        style={{ hangingPunctuation: "first" }}
      >
        {role.description}
      </p>

      {/* 底部签名行 —— dashed rule + emoji + 职责 */}
      <div className="mt-3 flex items-center gap-2 border-t border-dashed border-foreground/20 pt-2">
        <span className="text-[1.1rem] leading-none" aria-hidden>
          {role.birdEmoji}
        </span>
        <span className="h-px flex-1 bg-foreground/15" />
        <span className="font-mono text-[9px] uppercase tracking-wider text-foreground/45">
          {role.responsibility}
        </span>
      </div>

      {/* hover 时出现的啄痕 —— 右上角红色校字 */}
      <span
        aria-hidden
        className="tilt-a absolute -right-[2px] top-4 font-mono text-[11px] text-pecker-red/80 opacity-0 transition-opacity duration-400 group-hover:opacity-100"
      >
        ✱ 校
      </span>
    </article>
  );
}
