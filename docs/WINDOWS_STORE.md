# Windows 独立窗口与 Microsoft Store 发布

独立窗口、安装包和商店上架是三个交付环节。轻记的 React 页面可在 WebView2 桌面窗口中运行，Python 后端仍只在本机工作；无需为了上架改成云服务。本仓库提供 MSIX 构建脚本，尚未代用户注册开发者身份或提交商店审核。

## 先构建桌面程序

在 Windows x64 上构建并完成桌面自检：

```powershell
.venv\Scripts\python.exe scripts\build_windows.py --no-copy
.venv\Scripts\python.exe scripts\collect_notices.py --fetch-missing
```

构建环境需要 Windows SDK（`MakeAppx.exe`）。安装程序运行时还需要 Microsoft Edge WebView2 Runtime；不能仅因为开发电脑已有 Runtime 就视为用户电脑也已满足。应在干净电脑上测试缺失 Runtime 时的提示和恢复流程。微软提供 Evergreen 与 Fixed Version 两种分发策略；当前程序使用系统 Evergreen Runtime，不把整个浏览器放入 EXE。[WebView2 分发说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)

## 生成开发测试包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_msix.ps1 `
  -Version 1.2.0.0 -DevelopmentIdentity
```

输出在 `dist/msix/`，名称包含 `development-unsigned`，旁边的 JSON 记录 SHA256、载荷白名单和开发身份。脚本会先跑 EXE 的离线自检，再调用 SDK 的 MakeAppx 且不关闭清单验证。它只收集 EXE、现有图标生成的 PNG、LICENSE、第三方声明和隐私说明；不收集数据库、密钥、日志或开发目录。

此开发身份不是 Partner Center 身份，产物也没有数字签名，**不是可双击分发的正式安装包**。本脚本不会创建或安装证书，也不改变系统开发者设置。需要实际安装验证时，可在独立测试电脑上使用自行管理的开发签名/开发模式，遵循微软的测试安装说明。[MSIX 手工打包](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-manual-conversion)、[MakeAppx](https://learn.microsoft.com/en-us/windows/msix/package/create-app-package-with-makeappx-tool)

## 使用真实商店身份生成包

发布者先登录 [Microsoft Store 开发者入口](https://storedeveloper.microsoft.com/)，完成账户与身份核验，保留应用名称。在 Partner Center 的产品身份页面复制三个值，不要用 GitHub 用户名、示例 GUID 或开发身份代替：

| 脚本参数 | Partner Center 字段 |
| --- | --- |
| `-IdentityName` | Package/Identity/Name |
| `-Publisher` | Package/Identity/Publisher |
| `-PublisherDisplayName` | Package/Properties/PublisherDisplayName |

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_msix.ps1 `
  -Version 1.2.0.0 `
  -IdentityName '从产品身份页面复制' `
  -Publisher '从产品身份页面复制，包括 CN=' `
  -PublisherDisplayName '从产品身份页面复制' `
  -DisplayName '商店中保留的应用名称'
```

这些示例占位值不可直接提交。清单身份的大小写、空格和标点都必须匹配；四段包版本的末段留为 `0`，更新时提高版本。Microsoft Store 接受 MSIX，并在通过认证后使用微软证书重新签名；这一渠道无需先购买 CA 代码签名证书。直接在商店外分发 MSIX 的签名要求不同。[官方包与签名要求](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements)

开发者注册与身份核验必须由实际发布者本人完成。微软当前说明的新注册流程不收注册费，账户选项及可用流程应以注册页面为准。[官方开户说明](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account)

## 便携版与安装版的数据迁移

便携 EXE 使用同级 `data/quickmemory.db`，MSIX 使用 `%LOCALAPPDATA%/Packages/<PackageFamilyName>/LocalState/data/quickmemory.db`，不向只读的 `WindowsApps` 安装目录写数据。`QUICKMEMORY_DB` 环境变量可以覆盖数据库路径。两版的数据目录不同，安装 MSIX 不会自动导入便携版的题库或历史。

迁移完整数据时，先退出两种版本（确保后台评分和进程都已停止），分别备份源目录与目标目录，再将便携版 `data` 中的数据库文件复制到对应的 MSIX `LocalState/data`；不要在应用运行时复制 SQLite 文件，不要覆盖尚未备份的目标数据，也不复制 `.runtime.json`、实例锁或临时文件。完整数据库包含模型密钥，应仅在自己的可信电脑上迁移。若只迁移题库，可以使用文件夹 JSON 导出再导入；JSON 不含考试历史、评分记录或模型设置，不能替代完整数据库备份。

## 提交前的剩余工作

1. 在独立测试环境实际安装、首次启动、退出、重复打开、重启、升级和卸载；验证安装位置只读时仍能持久保存题库和设置，且老版本数据不会被覆盖。
2. 测试文件导入和 JSON 导出、Windows 缩放/键盘输入、断网、缺少 WebView2、后台评分关闭后的恢复。用 Windows App Certification Kit 做发布检查，保留报告。MakeAppx 成功只说明打包验证通过，不等于上述测试或商店认证通过。
3. 提供真实桌面窗口截图、简体中文简介、支持信息、年龄分级和有效隐私政策 URL。核对 [PRIVACY.md](PRIVACY.md) 的准备稿并补齐正式发布者非公开联系方式，再发布为无需登录即可访问的页面。应用会按用户操作把内容发送给配置的模型服务，隐私声明不能写成“所有内容永不离开电脑”。[隐私政策与支持信息](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/support-info)
4. 清单声明 `runFullTrust`，因为程序需要运行本机 Python 后端、SQLite 和原生桌面窗口。在审核备注里说明用途；受限能力需要提供说明，是否获准由商店认证决定。[能力声明说明](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/app-capability-declarations)
5. 上传使用真实身份构建的 MSIX，填完商店条目后提交审核。审核人员需要可操作的 AI 功能验证方案；不要在仓库、公开截图或日志中嵌入发布者私人 API 密钥。需提供临时测试凭证时，由发布者通过审核专用渠道自行配置。

建议的简体中文简介：

> 轻记是一款本地概念记忆工具。整理术语和参考定义，按文件夹随机默写，查看多裁判评分、错误类型与历史趋势。题库和学习记录保存在当前电脑；AI 功能需要自行配置兼容的模型服务与 API 密钥，相关调用可能由服务商收费。

建议的审核能力说明（按最终版本核对）：

> QuickMemory is a local, single-user study application. The runFullTrust capability is used for its bundled Python runtime, local SQLite database, native window, and a loopback-only HTTP backend. The application does not install a Windows service or require administrator privileges. AI requests are sent only to the provider configured by the user. Core card editing, import/export, and history browsing work without a model API key.

本文件记录的是可复用发布流程。生成 `store-unsigned.msix` 仅表示提供了身份参数；并不表示身份已经由 Microsoft 验证、应用已经上架或通过认证。
