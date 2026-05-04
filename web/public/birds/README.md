# Bird lg portraits · 手绘大头像资源

5 上线鸟的 lg 尺寸（lg = 32px / 同时也复用到 64-128px 显示场景）走 hand-drawn PNG。
sm/md 不需要图，走 BirdLabel（色点 + 文字）或 BirdArt-v2 SVG 线稿。

## 必需文件

```
biz-lg.png       业务鸟 · 红橙头冠 + 记事本
data-lg.png      数据鸟 · 圆框眼镜 + jade 羽毛
ux-lg.png        体验鸟 · 暖橙黄渐变 + 头微倾
risk-lg.png      风险鸟 · charcoal + 橙围巾 + wide-eye
goshawk-lg.png   苍鹰 · B&W + 圆瞳 + 高视角
```

## 规格要求

- **格式**：透明 PNG（alpha channel 必须保留，**不能**是黑/白/绿/品红 chroma-key 底）
- **尺寸**：1024×1024 源文件，框定圆形肖像 + 边缘留 8-12% 安全留白
- **风格**：editorial 手绘 + 暖白圆框 + charcoal 笔触（参考已生成的 5 张系列插画）
- **色板**：业务橙 / 数据 jade / 体验暖橙黄 / 风险 charcoal+橙 / 苍鹰 B&W

## 集成路径

`components/birds/BirdAvatar.tsx` 的 lg 分支会从这里读取，文件名硬编码在
`LG_PORTRAIT` 字典里。如果改名,记得同步改字典。

## 重新生成

prompt 全集见会话 archive `啄木鸟-pecker-v8/wiki/bird-portrait-prompts.md`
（如未归档，去对话里翻"5 鸟头像 Prompt · 完整版"那一段）。

## 文件不存在时的降级行为

BirdAvatar 不会崩——浏览器会显示 broken image 占位。后续如果要严格降级，
可以加 onError 兜底回 BirdArt-v2 SVG 线稿。
