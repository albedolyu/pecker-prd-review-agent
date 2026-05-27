/**
 * / — Pecker首页(赛博童话森林)
 *
 * 用户打开 root 第一眼看到的画面。不再 redirect /review,
 * 而是一片由数字组成的森林,中间一只Pecker从树洞里探头看你。
 *
 * 结构(server component 外壳 + 一个 client 组件做 canvas):
 * - 全屏深绿黑底 + canvas matrix 数字雨(client)
 * - 中间一个木纹"树洞"圆,里面一只大 emoji Pecker
 * - 树洞上方刊头 + 树洞下方"垂下来的藤蔓"导航 3 个入口
 *   (进入编辑部 / 关于家族 / 直接去评审)
 * - 整体色调:jungle emerald + 纸质米白点缀,像童话书的夜景插页
 */

import type { Metadata } from "next";
import { ForestLanding } from "./ForestLanding";

export const metadata: Metadata = {
  title: "Pecker · PRD 评审工作台",
  description:
    "提交 PRD 前做一次结构化检查,把目标范围、字段口径、体验细节和实现风险收成可确认清单。",
};

export default function HomePage() {
  return <ForestLanding />;
}
