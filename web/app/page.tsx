/**
 * / — 啄木鸟首页(赛博童话森林)
 *
 * 用户打开 root 第一眼看到的画面。不再 redirect /review,
 * 而是一片由数字组成的森林,中间一只啄木鸟从树洞里探头看你。
 *
 * 结构(server component 外壳 + 一个 client 组件做 canvas):
 * - 全屏深绿黑底 + canvas matrix 数字雨(client)
 * - 中间一个木纹"树洞"圆,里面一只大 emoji 啄木鸟
 * - 树洞上方刊头 + 树洞下方"垂下来的藤蔓"导航 3 个入口
 *   (进入编辑部 / 关于家族 / 直接去评审)
 * - 整体色调:jungle emerald + 纸质米白点缀,像童话书的夜景插页
 */

import type { Metadata } from "next";
import { ForestLanding } from "./ForestLanding";

export const metadata: Metadata = {
  title: "啄木鸟 · 一本每天出刊的评审笔记",
  description:
    "一只鸟加无数次回声,比一百只鸟凭直觉乱啄要可靠得多。欢迎进入编辑部。",
};

export default function HomePage() {
  return <ForestLanding />;
}
