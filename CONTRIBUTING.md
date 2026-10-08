# 贡献指南

感谢帮助改进轻记。问题反馈和功能建议请提交到 [Issues](https://github.com/healther3/QuickMemory/issues)，说明操作步骤、预期行为、实际结果、系统和应用版本。截图或日志请先脱敏，不要上传真实 API 密钥、数据库、个人题库或答题历史。

## 开始开发

按 [README](README.md) 完成源码安装，再安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run.py --dev
```

macOS / Linux 将 Python 路径替换为 `.venv/bin/python`。修改前阅读 [产品说明](docs/PRODUCT_CONTEXT.md)、[核心契约](docs/CORE_CONTRACT.md) 和 [API 契约](docs/API_CONTRACT.md)。UI 修改参考 [设计规范](design-system/quickmemory/MASTER.md)。

请保持以下行为：

- 应用在本机供单人使用，只有用户配置的模型接口需要运行时外网请求；界面与反馈使用简体中文。
- 用户参考定义是唯一评分标准，模型知识提示单独展示且不计分。全部裁判失败时保留“未评分”，不能补造分数。
- 用户标签与评分错误类型分别管理；修改或删除卡片不会改变历史答案快照。
- 不提交 `data/`、`.qa/`、日志、数据库、`.env`、真实密钥、个人配置或生成的发行 EXE。测试使用临时数据库与模拟 LLM，不读取开发者真实凭证。

## 提交修改

Fork 仓库，在新分支中完成聚焦的修改，再发起 Pull Request。说明解决的问题、修改后的行为和验证方法。数据库或 API 契约变更需同时说明兼容性与迁移影响，并更新对应文档。

根据修改范围运行相关验证；涉及核心流程时运行完整测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

当前验证基线为 162 项后端测试和 7 项前端交互测试，详见 [验证记录](docs/VALIDATION.md)。测试通过不代表真实服务商接口或模型语义质量已得到验证；如自行做过真实调用，请明确区分并避免提交响应中的敏感内容。

修改 API 后同步导出契约与前端类型：

```powershell
.\.venv\Scripts\python.exe scripts/export_openapi.py
npm --prefix frontend run types:api
```

Windows 打包入口与发行自检见 README 的“重新打包 Windows EXE”。构建包只能包含应用资源，不得包含开发者的数据、密钥或日志。

提交贡献即表示你有权提供这些修改，并同意按项目的 [MIT License](LICENSE) 分发。
