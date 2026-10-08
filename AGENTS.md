# QuickMemory 项目上下文

开始项目工作前阅读 `docs/PRODUCT_CONTEXT.md`（用户原始完整产品说明）、`docs/PHASES.md` 和 `docs/CORE_CONTRACT.md`。

- 原说明要求四阶段交付；用户于 2026-10-07 在第 1 阶段后明确要求“直接往后做吧”，已授权继续完成剩余阶段，不再逐阶段停下来确认。
- 本机单人应用：Python / FastAPI / SQLite；前端 React / Vite / TypeScript。无登录、部署、云同步；运行时网络请求仅用于配置的 LLM API。
- 所有界面和 LLM 反馈使用简体中文。内容为纯文本。
- 评分唯一标准是用户参考定义；模型知识提示不计分，也不生成错误标签。不得伪造 LLM 分数或把失败结果当作零分。
- 前端实施使用 `ui-ux-pro-max`，读取 `design-system/quickmemory/MASTER.md`，有对应页面规则时一并阅读；只用本地字体和资源。
- 保持已建立数据库及共享数据契约。修改契约时更新文档并明确告知用户。
- 测试入口：`.venv/Scripts/python.exe -m pytest -q`（Windows）；其他平台使用 `.venv/bin/python`。
- 测试模拟 LLM，不读取或输出真实密钥。真实模型验证需使用用户自行配置的凭证，并如实区分与模拟测试。
- Windows 日常使用 `轻记.exe`，源码入口 `desktop.py` + 原生托盘；发行构建用 `scripts/build_windows.py`。EXE 同级 `data` 为持久数据库，临时解包目录仅放资源；不得将用户数据库、密钥或日志打进发行包。构建脚本通过本机模拟接口的冻结自检后才替换发行 EXE。
