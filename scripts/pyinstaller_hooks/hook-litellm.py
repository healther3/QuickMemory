"""Bundle LiteLLM's local resources and registry-based lazy imports.

Do not import every SDK subpackage: the unused proxy has optional integrations
and importing them during analysis can initialize external services.
"""
import ast
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, get_package_paths

_, package_dir = get_package_paths("litellm")
package = Path(package_dir)
datas = collect_data_files(
    "litellm", includes=["**/*.json", "litellm_core_utils/tokenizers/*"],
    excludes=["**/__pycache__", "**/*.pyc"],
)
# Registry entries are strings, so static analysis cannot discover them.
registry = ast.parse((package / "_lazy_imports_registry.py").read_text(encoding="utf-8"))
hiddenimports = sorted({
    node.value for node in ast.walk(registry)
    if isinstance(node, ast.Constant) and isinstance(node.value, str)
    and node.value.startswith("litellm.")
    and ((package.parent / node.value.replace(".", "/")).with_suffix(".py").is_file()
         or (package.parent / node.value.replace(".", "/") / "__init__.py").is_file())
})
hiddenimports += ["litellm.main", "litellm.utils", "litellm.cost_calculator",
                  "litellm.litellm_core_utils.default_encoding", "tiktoken_ext.openai_public"]
