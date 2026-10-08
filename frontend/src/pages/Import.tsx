import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, FileJson, Upload } from "lucide-react";
import {
  message,
  send,
  useLoad,
  type Folder,
  type ImportInput,
  type ImportReport,
} from "../api";
import { Back, ErrorBox, PageHeader, Pill, Stat, Status } from "../ui";
const actionNames = {
  add: "新增",
  skip: "跳过",
  overwrite: "覆盖",
  invalid: "无效",
};
export default function Import() {
  const [params] = useSearchParams();
  const folders = useLoad<Folder[]>("/folders");
  const [form, setForm] = useState<ImportInput>({
    content: "",
    filename: "",
    folder_id: params.get("folder_id") ? Number(params.get("folder_id")) : null,
    folder_name: "",
    duplicate_mode: "skip",
  });
  const [report, setReport] = useState<ImportReport | null>(null),
    [done, setDone] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [showAll, setShowAll] = useState(false);
  function update<K extends keyof ImportInput>(key: K, value: ImportInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setReport(null);
    setDone(false);
    setError("");
  }
  async function readFile(file?: File) {
    if (!file) return;
    try {
      const content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
      setForm((f) => ({
        ...f,
        content: content.replace(/^\uFEFF/, ""),
        filename: file.name,
        folder_name: f.folder_name || file.name.replace(/\.json$/i, ""),
      }));
      setReport(null);
      setDone(false);
      setError("");
    } catch {
      setError("无法读取文件，请确认文件为 UTF-8 编码的 JSON。");
    }
  }
  async function preview() {
    setBusy(true);
    setError("");
    try {
      setReport(await send<ImportReport>("/imports/preview", form));
      setDone(false);
      setShowAll(false);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!report) return;
    setBusy(true);
    setError("");
    try {
      setReport(
        await send<ImportReport>("/imports/confirm", {
          ...form,
          preview_token: report.preview_token,
        }),
      );
      setDone(true);
      folders.reload();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Back />
      <PageHeader
        eyebrow="把已有知识带进来"
        title="导入题库"
        description="上传 JSON 文件，或直接粘贴内容。预览确认后，再写入你的概念库。"
      />
      <ol className="steps">
        <li className="active">
          <span>{report ? <Check size={15} /> : 1}</span>准备内容
        </li>
        <li className={report ? "active" : ""}>
          <span>{done ? <Check size={15} /> : 2}</span>核对预览
        </li>
        <li className={done ? "active" : ""}>
          <span>3</span>完成导入
        </li>
      </ol>
      <ErrorBox error={error || folders.error} />
      {done && (
        <Status>导入已完成，报告保留在下方。此次操作没有触发 AI 核对。</Status>
      )}
      <div className="import-grid">
        <section className="panel">
          <label className="file-drop">
            <FileJson size={32} strokeWidth={1.4} aria-hidden="true" />
            <strong>{form.filename || "选择一个 JSON 文件"}</strong>
            <span>支持 UTF-8 / UTF-8 BOM 编码</span>
            <input
              type="file"
              accept=".json,application/json"
              aria-label="选择 JSON 文件"
              disabled={busy}
              onChange={(e) => readFile(e.target.files?.[0])}
            />
          </label>
          <label className="field">
            或粘贴 JSON 内容
            <textarea
              className="code-input"
              rows={11}
              spellCheck={false}
              value={form.content}
              placeholder={
                '{\n  "过拟合": "模型在训练集表现好，在新数据上泛化差。"\n}'
              }
              onChange={(e) => update("content", e.target.value)}
            />
          </label>
          <details className="format-help">
            <summary>查看支持的两种格式</summary>
            <p>简单对象：术语 → 参考定义</p>
            <pre>{'{ "术语": "参考定义" }'}</pre>
            <p>数组对象：还可以包含用户标签和参考笔记</p>
            <pre>
              {
                '[{ "term": "术语", "definition": "参考定义", "tags": ["标签"], "reference_note": "选填" }]'
              }
            </pre>
          </details>
        </section>
        <section className="panel import-options">
          <h2>导入选项</h2>
          <label className="field">
            目标文件夹
            <select
              value={form.folder_id ?? ""}
              onChange={(e) =>
                update(
                  "folder_id",
                  e.target.value ? Number(e.target.value) : null,
                )
              }
            >
              <option value="">新建文件夹</option>
              {folders.data?.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
          {form.folder_id === null && (
            <label className="field">
              新文件夹名称
              <input
                value={form.folder_name}
                placeholder={
                  form.filename.replace(/\.json$/i, "") || "为这份题库命名"
                }
                onChange={(e) => update("folder_name", e.target.value)}
              />
            </label>
          )}
          <fieldset>
            <legend>遇到同名术语时</legend>
            <label className="radio-option">
              <input
                type="radio"
                name="duplicate"
                checked={form.duplicate_mode === "skip"}
                onChange={() => update("duplicate_mode", "skip")}
              />
              <div>
                <strong>跳过</strong>
                <span>保留已有卡片的定义。</span>
              </div>
            </label>
            <label className="radio-option">
              <input
                type="radio"
                name="duplicate"
                checked={form.duplicate_mode === "overwrite"}
                onChange={() => update("duplicate_mode", "overwrite")}
              />
              <div>
                <strong>覆盖定义</strong>
                <span>
                  用导入内容更新已有卡片；共享卡片的其他文件夹也会同步变化。
                </span>
              </div>
            </label>
          </fieldset>
          <button
            className="button primary full"
            disabled={busy || !form.content.trim()}
            onClick={preview}
          >
            <Upload size={17} aria-hidden="true" />
            {busy ? "正在处理…" : "生成导入预览"}
          </button>
          <p className="field-hint">
            只在确认导入后修改卡片。术语会去除首尾空格，并忽略大小写进行匹配。
          </p>
        </section>
      </div>
      {report && (
        <section className="panel import-report">
          <div className="section-heading">
            <h2>{done ? "导入报告" : "导入预览"}</h2>
            {done ? (
              <Link
                className="button primary"
                to={`/cards?folder_id=${report.folder_id}`}
              >
                查看已导入卡片
              </Link>
            ) : (
              <button
                className="button primary"
                disabled={busy}
                onClick={confirm}
              >
                {busy ? "正在导入…" : "确认导入"}
              </button>
            )}
          </div>
          <div className="stats-strip four">
            <Stat label="新增" value={report.added} />
            <Stat label="跳过" value={report.skipped} />
            <Stat label="覆盖" value={report.overwritten} />
            <Stat label="无效" value={report.invalid} />
          </div>
          <div className="report-table">
            {(showAll ? report.rows : report.rows.slice(0, 8)).map(
              (row, index) => (
                <div className="report-row" key={index}>
                  <Pill
                    tone={
                      row.action === "invalid"
                        ? "red"
                        : row.action === "add"
                          ? "green"
                          : "neutral"
                    }
                  >
                    {actionNames[row.action]}
                  </Pill>
                  <div>
                    <strong>{row.term || "空术语"}</strong>
                    {row.definition && (
                      <p className="plain-text">{row.definition}</p>
                    )}
                    {row.reason && <p className="field-hint">{row.reason}</p>}
                  </div>
                </div>
              ),
            )}
          </div>
          {report.rows.length > 8 && (
            <button
              className="text-button"
              onClick={() => setShowAll(!showAll)}
            >
              {showAll ? "收起报告" : `查看全部 ${report.rows.length} 条明细`}
            </button>
          )}
        </section>
      )}
    </>
  );
}
