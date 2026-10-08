# QuickMemory 前端

React + Vite + TypeScript 本地学习工作台。用户已授权直接完成全部后续阶段。

项目的完整需求保存在 `../docs/PRODUCT_CONTEXT.md`，阶段约定见 `../docs/PHASES.md`。已按用户要求使用 `ui-ux-pro-max` 制定设计，见 `../design-system/quickmemory/MASTER.md`；检索和约束适配见同目录 `RESEARCH.md`。

已实现卡片管理与编辑、AI 核对、文件夹、导入预览与报告、考试、考试结果、统计看板、卡片历史和设置。界面与系统反馈使用简体中文，卡片正文为纯文本。核心 API 类型从后端 OpenAPI 自动生成，`src/api.ts` 提供简洁别名和统一错误处理。

界面与资源完全本地加载，不使用远程字体、CDN、外部图片、登录或云端同步。考试提交后立即进入下一题，结果页轮询评分；模型知识提示保持独立并明确“不计分”。

考试草稿与首次提交的精确请求暂存在当前浏览器；提交响应丢失时重发相同文本和耗时。结果与历史每两秒轮询，全部评分结束后停止。未评分不显示零分，人工编辑错误类型期间不会被其他题目的轮询覆盖。

开发与构建命令（在本目录执行）：

```powershell
npm install
npm run dev
npm run build
npm test
```

Vite 绑定 `127.0.0.1:5173`，将 `/api` 代理到 `127.0.0.1:8000`。后端使用其他端口时先设置 `$env:QUICKMEMORY_API_PORT="端口"`。完整开发模式及生产单命令启动见项目根 README。

后端契约更新后，在根目录运行 `.venv/Scripts/python.exe scripts/export_openapi.py`，再在本目录运行 `npm run types:api`。输出保存至 `src/generated/api-schema.d.ts`，不连接 LLM 或读取密钥。

设计采用本机字体与打包的 Lucide SVG。界面使用 CSS 语义令牌、响应式布局、键盘焦点与减少动态效果支持。`npm run format` 只格式化源码与 Vite 配置。
