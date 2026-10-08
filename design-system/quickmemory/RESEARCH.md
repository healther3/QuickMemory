# ui-ux-pro-max 检索与适配记录

日期：2026-10-07。工具：本地 `ui-ux-pro-max/scripts/search.py`，使用已有 Python 运行时。检索没有发送任何项目私有数据到网络。用户已明确要求使用本技能。

## 产品分析

产品类型：个人学习工具与本地内容管理。用户任务：录入概念、核对参考定义、默写、异步查看反馈、分析错误。平台：桌面 Web，兼顾窄屏。栈：React / Vite / TypeScript。目标风格：简洁、文字优先、安静、数据清楚。

## 查询与验证

| 查询 | 模式 | 实际首项 | 验证结论 |
| --- | --- | --- | --- |
| `learning productivity minimal dashboard` | `--design-system` | Pattern: Product Demo + Features；Style: AI-Native UI | 不适合本地学习工作台。没有采用聊天界面、视频、营销结构或远程字体。按技能要求缩窄重试一次。 |
| `personal productivity notes minimalist` | `--design-system --variance 2 --density 6` | Pattern: Product Demo + Features；Style: Minimalism & Swiss Style | 整体页面模式仍不匹配，因此没有保存原始生成系统。已验证的简约风格和低装饰方向适合本产品；青绿色用于推导本项目墨绿配色。 |
| `minimalism functional` | `--domain style -n 2` | `minimalism-and-swiss-style`，General，active | 匹配功能性工具：网格、留白、高对比、无多余装饰。仅采用适合工作台的规则，不采用结果文案里的 landing page 结构。 |
| `forms async state` | `--stack react` | Concurrency: Use Actions with async startTransition | 栈匹配。控制表单状态和捕获异步错误适用；React 19 专属建议仅在最终版本匹配后采用，不要求升级依赖，也不把 transition 当作后台任务持久化方案。 |
| `error summary validation` | `--domain ux -n 3` | Forms / Accessibility: Focusable Error Summary，Web | 精确匹配表单错误。采用可聚焦错误摘要、字段链接、保留行内错误。 |
| `distribution comparison bar` | `--domain chart -n 2` | Geographic Data: Choropleth / Bubble Map | 首项与产品不符，未采用；按规则缩窄重试。 |
| `ranking` | `--domain chart -n 2` | Compare Categories: Bar Chart | 匹配离散错误类型计数。采用横向条形图、直接数字标签和表格替代，不照抄“每条不同颜色”的非必要建议。 |

## 持久化说明

本次未找到完整匹配本产品的自动设计系统；没有使用 `--persist` 把未经验证的营销布局、网络字体或聊天效果写入项目。`MASTER.md` 为人工综合设计，明确采用已验证的局部结果，并以产品硬约束修订。该处理符合技能“Do not persist unverified output”的要求。

主要适配：

1. 在线 Google Fonts 替换成本机中文字体；禁止 CDN、在线图标与外部图片。
2. 营销首页替换为可操作的卡片/文件夹工作台。
3. 生成结果的浅青绿底和亮橙按钮调整为纸底、深绿主操作；暖色只隔离不计分提示。
4. AI 聊天/流式动画替换成异步评分状态；本产品调用非流式 JSON 接口。
5. 排名和分布只呈现实际统计，不引入记忆强弱分类。
6. 第 1 阶段只保存未来设计决策；实际 UI、组件和浏览器验证在用户确认进入第 3 阶段后进行。

## 验证边界

颜色对比值已用 WCAG 相对亮度公式计算，列于 `MASTER.md`。没有 UI 代码，因此尚未声称完成视觉截图、浏览器行为或读屏验收。完整实现前必须按规范再验证。
