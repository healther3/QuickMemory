# 第三方组件与许可

QuickMemory 自有代码的许可见根目录 `LICENSE`。第三方组件保留其各自的版权声明、许可与通知；本项目的许可不替代它们。

运行依赖版本见 `requirements-lock.txt` 和 `frontend/package-lock.json`。Windows 发行包另使用 Python 解释器、PyInstaller bootloader 及相关运行库。源码仓库不包含用户数据、依赖目录或编译后的 EXE。

每个 Windows Release 随附 `THIRD_PARTY_NOTICES.txt`，按实际安装的包名、版本保留完整许可和 NOTICE 文本，包括：

- Python 解释器的 `LICENSE.txt`（包含其第三方通知）。
- `requirements.txt` 解析得到的已安装 Python 运行依赖及传递依赖。
- npm 锁文件中非开发依赖的完整许可文本。
- PyInstaller 的 `COPYING.txt`（含 bootloader 例外）与 hooks 的许可文本。

在构建发行包所用的 Python 环境及完成 `npm ci` 后，运行：

```powershell
.\.venv\Scripts\python.exe scripts\collect_notices.py --fetch-missing
```

输出为 `dist/THIRD_PARTY_NOTICES.txt`，不包含机器路径或应用数据。收集器优先读取已安装组件的许可文件，遇到缺少全文的组件即报错，不根据许可名称猜测文本。目前 `tokenizers` 的 wheel 未提供许可文件，`--fetch-missing` 仅为它从[官方版本标签](https://github.com/huggingface/tokenizers)读取 `LICENSE`；该请求只发生在人工运行的发行准备脚本中。

发布或转发 Windows 程序时，请同时保留随附的项目 `LICENSE` 与第三方通知文件。对未修改第三方组件的相应版本源码，可从通知中的上游链接及 PyPI/npm 对应版本获取。
