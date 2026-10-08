# 第 1 阶段核心契约

本文件补充 PRODUCT_CONTEXT.md，不替换原始需求。完整业务路由清单已保存为 API_CONTRACT.md，机器契约为 openapi.json。

## 固定语义

- Python 使用 SQLAlchemy 2 与 Pydantic 2；数据库表名与原需求一致。
- `SettingsData` 是完整设置输入契约。查询输出调用 `public_dict()`，不返回 `api_key`，返回 `has_api_key`。
- `GradingService.grade(term=..., reference_definition=..., user_answer=..., settings=..., error_types=...)` 为异步入口，返回 `GradingResult`；网络期间不持有数据库 Session。
- `precheck(...)` 返回 `PrecheckFeedback`，不入库；页面必须显示 `AI 核对结果不一定正确，请自行复查`。
- `test_connection(settings)` 返回校验后的连接反馈，失败给出简体中文错误。
- 裁判编号 `judge_index` 从 **1** 开始（1–3）；考试题序 `position` 从 **0** 开始。
- `persist_grade(session, answer_id, result)` 原子替换裁判记录、分数、反馈和当前仍存在的错误类型关联，只 flush，由调用方 commit。
- `GradingResult.error` 写入数据库 `ExamAnswer.grading_error`；`merged_feedback` 只含 `correct_parts / wrong_parts / uncertain_parts / error_types`，模型提示单独存放。
- 没有任何成功裁判：`failed` + `accuracy/completeness/final_score=null`。未作答与待评分共用 `pending`，通过 `submitted_at` 是否为空区分，不能将未作答题加入后台评分。
- 评分正文只是普通文本，未来前端用 React 文本节点呈现，不使用 Markdown/HTML 渲染。

## 为后续阶段预留的增量字段

在原始最小数据模型上补充以下字段，不移除原有功能：

| 表 | 补充字段 | 用途 |
|---|---|---|
| exam_sessions | folder_name_snapshot, settings_snapshot | 保留考试名称及当时评分参数，不复制 API 密钥 |
| exam_answers | position, submitted_at | 持久保存随机题序，区分未作答与待评分 |
| exam_answers | disagreement, merge_fallback, grading_error | 表示裁判分歧、合并降级、未评分原因 |
| judge_results | raw_text, error | 留存无效 JSON 原文及中文失败原因 |
| settings | json_mode, request_timeout | 兼容不支持 JSON 参数的接口及请求超时 |
| app_meta（新增表） | key, value | 一次性示例初始化标记、错误类型 ID 高水位；不改变既有业务表 |

卡片、文件夹和重考父场次外键允许 `SET NULL`，删除实体不会删除历史答案快照。两个答案快照字段命名为 `term_snapshot` / `definition_snapshot`。统计只能平均已评分记录，不能将 `null` 当作 0；作答次数可包含已提交但评分失败的记录。

## 下一阶段必须继续遵守

1. 只绑定本机环回地址；业务写接口验证本地 Origin，无登录系统。关闭第三方 CDN 文档资源。
2. 出题前保存全部卡片快照和随机顺序；答题界面响应不得泄露参考定义。
3. 提交后尽快返回并独立排队，限制多个答案同时评分的总并发；恢复启动时处理已提交但遗留 pending 的记录。
4. 每场考试使用开始时设置快照；密钥从当前设置安全加载，不复制到历史。
5. 导入预览和确认共用解析/去重逻辑，UTF-8 BOM、修剪、casefold 去重；覆盖属于多个文件夹的同一卡片时应在预览中明确共享卡片也受影响。
6. 标签与计分错误类型是两个体系；删除/重命名错误类型时同步历史反馈展示和关联，后台结果不能复活已删除类型。
7. 重考只挑选已评分且低于阈值的题，不把 failed 当错题；保留 parent_session_id。
8. 后续 API 变更必须在此记录，与 React 数据类型保持一致；第 3 阶段优先从 FastAPI OpenAPI 生成类型。

## Windows 桌面包补充

用户后续要求免命令行一键启动，新增 `desktop.py` 与原生 Windows 托盘入口。数据库结构和业务 API 不变；EXE 读取自身所在目录的 `data/quickmemory.db`，不会把持久数据写入 PyInstaller 临时解包目录。源码与桌面入口共用同一文件锁。

启动器注册不进入 OpenAPI 的 `/api/_local_instance`：GET 验证同库运行实例，POST 请求有序退出。两者都需要保存在本机实例状态文件里的随机 256 位令牌；只通过环回地址访问，并继续受本地 Origin 限制。端口、数据库路径摘要与令牌用于重复启动协调，不是模型 API 密钥。状态文件在正常退出后移除。

## 本地服务控制补充

设置页新增 `GET/PUT /api/local-service`（当前地址、可否关闭及首选端口）与 `POST /api/local-service/stop`（有序关闭）。写请求继续受本地 Origin 限制；网页不接触实例令牌。只有 `desktop.py` / `run.py` 注入退出回调后允许网页关闭，直接 Uvicorn 启动时返回不支持。首选端口存放于数据库同目录 `launcher.json`，下次启动读取；命令行 `--port` 只覆盖当次。数据库结构、模型密钥和评分配置均不变。

## v1.2 独立窗口与商店打包

Windows EXE 默认用 pywebview 的 WebView2（Edge Chromium）渲染本机界面，FastAPI 在同进程后台线程运行。窗口关闭与后端退出双向联动；`--browser` 保留旧浏览器/托盘模式，`--no-browser` 保留自动验收用途。窗口仅允许当前环回 HTTP Origin（及其导出 Blob）导航，不提供自定义 Python JS API；编辑页通过无内容的布尔标记支持原生关闭前确认。

`GET/PUT /api/local-service` 新增 `desktop_window` 布尔值，驱动桌面模式的设置文案。新增不进入 OpenAPI 的 `POST /api/_local_instance/activate`，使用已有随机实例令牌授权并唤起同库窗口；与退出路由独立，避免调用旧版实例时误关闭。

便携版仍读写 EXE 同级 `data`；通过 Windows Package Family Name 识别 MSIX 进程后，使用 `%LOCALAPPDATA%/Packages/<PFN>/LocalState` 下的 `data`、`logs` 和 `webview`，不会向只读安装目录写入。`QUICKMEMORY_DB` 显式指定测试或自选数据库时，日志与窗口缓存跟随该数据目录。两类发行渠道数据不自动互相迁移，数据库结构及既有设置不变。

MSIX 脚本限定载荷白名单，并在打包前运行冻结自检。真实商店构建必须明确输入 Partner Center 的三项身份；开发身份包另行命名并明确未签名、未提交。MakeAppx 验证不代表实际安装、升级、WACK 或商店认证已经通过。
