import { useEffect, useRef, useState } from "react";
import {
  Link,
  useNavigate,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { Check, History, Save, Sparkles, Trash2 } from "lucide-react";
import {
  api,
  message,
  send,
  useLoad,
  type Card,
  type CardInput,
  type Folder,
  type Precheck,
  type Tag,
} from "../api";
import { Back, ErrorBox, Loading, PageHeader, Status, TextList } from "../ui";
export default function Editor() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const routeLocation = useLocation();
  const returnTo =
    typeof routeLocation.state?.returnTo === "string" &&
    routeLocation.state.returnTo.startsWith("/cards")
      ? routeLocation.state.returnTo
      : "/cards";
  const loaded = useLoad<Card>(id ? `/cards/${id}` : null);
  const folders = useLoad<Folder[]>("/folders"),
    tags = useLoad<Tag[]>("/tags");
  const [form, setForm] = useState<CardInput>({
    term: "",
    definition: "",
    reference_note: "",
    tags: [],
    folder_ids: params.get("folder_id")
      ? [Number(params.get("folder_id"))]
      : [],
  });
  const [tagInput, setTagInput] = useState(""),
    [busy, setBusy] = useState(false),
    [checking, setChecking] = useState(false),
    [error, setError] = useState(""),
    [checkError, setCheckError] = useState(""),
    [success, setSuccess] = useState(""),
    [precheck, setPrecheck] = useState<Precheck | null>(null);
  const initial = useRef(JSON.stringify(form));
  useEffect(() => {
    if (loaded.data) {
      const c = loaded.data;
      const value = {
        term: c.term,
        definition: c.definition,
        reference_note: c.reference_note || "",
        tags: c.tags.map((t) => t.name),
        folder_ids: c.folders.map((f) => f.id),
      };
      setForm(value);
      initial.current = JSON.stringify(value);
    }
  }, [loaded.data]);
  const dirty = JSON.stringify(form) !== initial.current || !!tagInput.trim();
  useEffect(() => {
    window.__quickMemoryHasUnsavedChanges = dirty;
    return () => {
      window.__quickMemoryHasUnsavedChanges = false;
    };
  }, [dirty]);
  useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  useEffect(() => {
    if (!dirty) return;
    const guard = (event: MouseEvent) => {
      const anchor = (event.target as Element).closest("a");
      if (
        anchor &&
        anchor.origin === location.origin &&
        anchor.pathname !== location.pathname &&
        !window.confirm("卡片尚未保存，确认离开并放弃修改？")
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("click", guard, true);
    return () => document.removeEventListener("click", guard, true);
  }, [dirty]);
  function update<K extends keyof CardInput>(key: K, value: CardInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setSuccess("");
  }
  function addTag() {
    const values = tagInput
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    update("tags", [...new Set([...form.tags, ...values])]);
    setTagInput("");
  }
  async function save() {
    if (!form.term.trim() || !form.definition.trim()) {
      setError("请填写术语和参考定义。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const value = {
        ...form,
        tags: [
          ...new Set([
            ...form.tags,
            ...tagInput
              .split(/[,，\n]/)
              .map((t) => t.trim())
              .filter(Boolean),
          ]),
        ],
      };
      const result = await send<Card>(
        id ? `/cards/${id}` : "/cards",
        value,
        id ? "PUT" : "POST",
      );
      initial.current = JSON.stringify(value);
      setForm(value);
      setTagInput("");
      setSuccess("卡片已保存在本机。");
      if (!id)
        navigate(`/cards/${result.id}/edit`, {
          replace: true,
          state: { returnTo },
        });
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function check() {
    setChecking(true);
    setCheckError("");
    setPrecheck(null);
    try {
      setPrecheck(
        await send<Precheck>("/precheck", {
          term: form.term,
          definition: form.definition,
          reference_note: form.reference_note,
        }),
      );
    } catch (e) {
      setCheckError(message(e));
    } finally {
      setChecking(false);
    }
  }
  async function remove() {
    if (
      !window.confirm(
        `永久删除「${form.term}」？将从全部文件夹移除；历史考试快照仍会保留。`,
      )
    )
      return;
    setBusy(true);
    try {
      await api(`/cards/${id}`, { method: "DELETE" });
      navigate("/cards");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  if (id && loaded.loading && !loaded.data) return <Loading />;
  return (
    <>
      <Back to={returnTo} />
      <PageHeader
        eyebrow={id ? "整理你的理解" : "一张卡片，一个概念"}
        title={id ? "编辑卡片" : "新建卡片"}
        description="用自己的语言，写下值得记住的定义。"
        actions={
          id ? (
            <Link
              className="button"
              to={`/cards/${id}/history`}
              state={{ returnTo }}
            >
              <History size={17} aria-hidden="true" />
              作答历史
            </Link>
          ) : undefined
        }
      />
      <ErrorBox error={error || loaded.error || folders.error || tags.error} />
      {success && <Status>{success}</Status>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
        className="editor-grid"
      >
        <section className="panel form-panel">
          <label className="field">
            术语 <span className="required">*</span>
            <input
              required
              maxLength={2000}
              placeholder="例如：过拟合"
              value={form.term}
              onChange={(e) => update("term", e.target.value)}
            />
          </label>
          <label className="field">
            参考定义 <span className="required">*</span>
            <span className="field-hint">
              考试评分的唯一标准；请尽量写清关键要点。
            </span>
            <textarea
              className="definition-input"
              required
              rows={9}
              placeholder="这个概念是什么？它的关键特征有哪些？"
              value={form.definition}
              onChange={(e) => update("definition", e.target.value)}
            />
          </label>
          <label className="field">
            参考笔记 <span className="optional">选填</span>
            <span className="field-hint">
              仅在 AI 核对时提供上下文，不用于考试评分。
            </span>
            <textarea
              rows={4}
              placeholder="可以粘贴教材或课程中的相关内容…"
              value={form.reference_note}
              onChange={(e) => update("reference_note", e.target.value)}
            />
          </label>
          <div className="form-bottom">
            <span className="muted">
              {dirty ? "有尚未保存的修改" : "内容已保存"}
            </span>
            <button className="button primary" disabled={busy || checking}>
              <Save size={17} aria-hidden="true" />
              {busy ? "正在保存…" : "保存卡片"}
            </button>
          </div>
        </section>
        <aside className="editor-aside">
          <section className="panel">
            <h2>整理卡片</h2>
            <label className="field">
              用户标签
              <span className="field-hint">
                输入后按回车，可用逗号分隔多个标签。
              </span>
              <div className="tag-entry">
                <input
                  list="known-tags"
                  value={tagInput}
                  placeholder="添加标签…"
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addTag();
                    }
                  }}
                />
                <button
                  type="button"
                  className="icon-button"
                  aria-label="添加标签"
                  onClick={addTag}
                >
                  <Check size={18} />
                </button>
              </div>
              <datalist id="known-tags">
                {tags.data?.map((t) => (
                  <option value={t.name} key={t.id} />
                ))}
              </datalist>
            </label>
            <div className="pills">
              {form.tags.map((tag) => (
                <button
                  type="button"
                  className="pill removable"
                  key={tag}
                  aria-label={`移除标签${tag}`}
                  onClick={() =>
                    update(
                      "tags",
                      form.tags.filter((t) => t !== tag),
                    )
                  }
                >
                  {tag}
                  <span aria-hidden="true">×</span>
                </button>
              ))}
            </div>
            <fieldset className="folder-checks">
              <legend>所属文件夹</legend>
              <p className="field-hint">一张卡片可放入多个文件夹。</p>
              {folders.data?.map((f) => (
                <label className="checkbox" key={f.id}>
                  <input
                    type="checkbox"
                    checked={form.folder_ids.includes(f.id)}
                    onChange={(e) =>
                      update(
                        "folder_ids",
                        e.target.checked
                          ? [...form.folder_ids, f.id]
                          : form.folder_ids.filter((i) => i !== f.id),
                      )
                    }
                  />
                  {f.name}
                </label>
              ))}
              {!folders.data?.length && (
                <Link to="/folders">先创建一个文件夹</Link>
              )}
            </fieldset>
          </section>
          <section className="panel precheck-intro">
            <Sparkles size={23} aria-hidden="true" />
            <h2>多一个参考视角</h2>
            <p>让模型核对定义，也可以提出澄清问题。最终内容由你决定。</p>
            <p className="disclaimer">AI 核对结果不一定正确，请自行复查</p>
            <button
              type="button"
              className="button full"
              disabled={
                checking || busy || !form.term.trim() || !form.definition.trim()
              }
              onClick={check}
            >
              {checking ? "正在核对…" : "AI 核对定义"}
            </button>
            <ErrorBox error={checkError} />
          </section>
          {id && (
            <button
              type="button"
              className="text-button danger-text"
              disabled={busy}
              onClick={remove}
            >
              <Trash2 size={17} aria-hidden="true" />
              永久删除卡片
            </button>
          )}
        </aside>
      </form>
      {precheck && (
        <section className="panel precheck-result">
          <div className="section-heading">
            <h2>AI 核对结果</h2>
            <span className="muted">不会自动保存</span>
          </div>
          <p className="notice warm">AI 核对结果不一定正确，请自行复查</p>
          <div className="feedback-grid">
            {[
              ["正确的部分", precheck.correct_parts],
              ["可能有误的部分", precheck.wrong_parts],
              ["不确定的部分", precheck.uncertain_parts],
            ].map(([title, items]) => (
              <div key={title as string}>
                <h3>{title as string}</h3>
                <TextList items={items as string[]} />
              </div>
            ))}
          </div>
          {precheck.clarifying_questions.length > 0 && (
            <>
              <h3>需要你澄清的问题</h3>
              <TextList items={precheck.clarifying_questions} />
            </>
          )}
          {precheck.suggested_rewrite && (
            <div className="rewrite">
              <h3>建议改写</h3>
              <p className="plain-text">{precheck.suggested_rewrite}</p>
              <button
                className="button"
                onClick={() =>
                  update("definition", precheck.suggested_rewrite!)
                }
              >
                采用建议改写
              </button>
              <span className="field-hint">采用后，请点击“保存卡片”。</span>
            </div>
          )}
        </section>
      )}
    </>
  );
}
