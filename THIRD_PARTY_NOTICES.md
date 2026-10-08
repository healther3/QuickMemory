# 第三方组件与许可

QuickMemory 自有代码的许可见根目录 `LICENSE`。第三方组件保留其各自的版权声明、许可与通知；本项目的许可不替代它们。

运行依赖版本见 `requirements-lock.txt` 和 `frontend/package-lock.json`。Windows 发行包另使用 Python 解释器、PyInstaller bootloader 及相关运行库。源码仓库不包含用户数据、依赖目录或编译后的 EXE。

每个 Windows Release 随附 `THIRD_PARTY_NOTICES.txt`，按实际安装的包名、版本保留完整许可和 NOTICE 文本，包括：

- Python 解释器的 `LICENSE.txt`（包含其第三方通知）。
- Python 本机运行库 OpenSSL、Expat、zlib、SQLite、libffi、liblzma 的上游许可/声明。
- `requirements.txt` 解析得到的已安装 Python 运行依赖及传递依赖。
- npm 锁文件中非开发依赖的完整许可文本。
- PyInstaller 的 `COPYING.txt`（含 bootloader 例外）与 hooks 的许可文本。
- 桌面窗口所用的 pywebview、pythonnet、clr_loader 等 Python 依赖，以及随 pywebview 分发的 Microsoft WebView2 SDK 二进制的独立许可与 NOTICE。

在构建发行包所用的 Python 环境及完成 `npm ci` 后，运行：

```powershell
.\.venv\Scripts\python.exe scripts\collect_notices.py --fetch-missing
```

输出为 `dist/THIRD_PARTY_NOTICES.txt`，不包含机器路径或应用数据。收集器优先读取已安装组件的许可文件，遇到缺少全文的组件即报错，不根据许可名称猜测文本。`--fetch-missing` 从官方版本标签读取缺失的 `tokenizers` 许可及本机库许可，并从固定上游提交读取 `proxy_tools` 许可；网络请求只发生在人工运行的发行准备脚本中。

`proxy_tools 0.1.0` 的 wheel 和 PyPI 源码包都没有附全文许可，元数据标为 MIT，但上游 `LICENSE.txt` 为含 Armin Ronacher 与 Jonathan Tushman 版权的 BSD 文本。本发行包原样保留该实际文本并明确这一差异；已经核对固定提交 `70b751ef5e0647d974506fd5871903711b5e1811` 的完整模块与已安装版本、PyPI 0.1.0 源码包一致，收集器固定验证模块与许可 SHA256。

OpenSSL、Expat、zlib、SQLite 的版本取自构建解释器运行时。此环境中 `libffi-8.dll` 和静态链接的 liblzma 不导出补丁版本：通知明确区分所附许可文本的上游版本与未核实的二进制版本，并保留 liblzma 历史公有领域和 0BSD 声明，不把它们标成 MIT。更换 Python 发行来源时，应重新检查其本机运行库清单。

发布或转发 Windows 程序时，请同时保留随附的项目 `LICENSE` 与第三方通知文件。对未修改第三方组件的相应版本源码，可从通知中的上游链接及 PyPI/npm 对应版本获取。

## WebView2 SDK

桌面版打包的 `Microsoft.Web.WebView2.Core.dll`、`Microsoft.Web.WebView2.WinForms.dll` 和 `WebView2Loader.dll` 来自 pywebview。它们不是 pywebview 自有 MIT 代码。当前 DLL 的版本是 `1.0.3856.49`；Core、WinForms 以及 x64/x86/arm64 三种 Loader 均已逐个比较 SHA256，与微软官方同版本 NuGet 包内的二进制一致。包含辅助 Loader 不表示本发行 EXE 支持所有架构，当前 EXE/MSIX 仍以 x64 为目标。

完整 SDK 许可与附加通知保存在 `licenses/webview2-1.0.3856.49/`。其中 `SOURCE.json` 记录官方下载地址、包 SHA256、各 DLL 及许可文件 SHA256；升级 pywebview 或替换 DLL 时必须重新核对，不能沿用旧版本的匹配结论。该版本官方 SDK 包的 `LICENSE.txt` 为微软版权的三条款 BSD 文本，`NOTICE.txt` 保留包内其他声明。这里只描述已核对的 SDK 文件，不把系统安装的 WebView2 Runtime 重新许可为 BSD；Runtime 由微软分发，本发行包不包含 Runtime。
