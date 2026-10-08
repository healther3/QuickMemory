import { useEffect, useRef, useState } from "react";
import {
  Eye,
  EyeOff,
  FlaskConical,
  KeyRound,
  Save,
  SlidersHorizontal,
  Tags,
} from "lucide-react";
import {
  message,
  send,
  useLoad,
  type Provider,
  type Settings as SettingsData,
} from "../api";
import NamedManager from "../NamedManager";
import LocalService from "../LocalService";
import { ErrorBox, Loading, PageHeader, Status } from "../ui";
export default function Settings() {
  const loaded = useLoad<SettingsData>("/settings"),
    providers = useLoad<Provider[]>("/providers");
  const [form, setForm] = useState<SettingsData | null>(null),
    [key, setKey] = useState(""),
    [clearKey, setClearKey] = useState(false),
    [showKey, setShowKey] = useState(false),
    [busy, setBusy] = useState<"save" | "test" | null>(null),
    [error, setError] = useState(""),
    [status, setStatus] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (loaded.data) setForm(loaded.data);
  }, [loaded.data]);
  function change<K extends keyof SettingsData>(
    name: K,
    value: SettingsData[K],
  ) {
    setForm((f) => (f ? { ...f, [name]: value } : f));
    setStatus("");
  }
  function providerChanged(id: string) {
    const value = providers.data?.find((p) => p.id === id);
    if (!value) return;
    setForm((f) =>
      f
        ? {
            ...f,
            provider: id,
            base_url: value.base_url,
            model: value.suggested_model,
          }
        : f,
    );
    setKey("");
    setClearKey(false);
    setStatus("");
  }
  function payload() {
    if (!form) return {};
    const { has_api_key, ...data } = form;
    return {
      ...data,
      ...(clearKey ? { api_key: "" } : key ? { api_key: key } : {}),
    };
  }
  async function act(action: "save" | "test") {
    if (!formRef.current?.reportValidity()) return;
    setBusy(action);
    setError("");
    setStatus("");
    try {
      if (action === "save") {
        const data = await send<SettingsData>("/settings", payload(), "PUT");
        setForm(data);
        loaded.setData(data);
        setKey("");
        setClearKey(false);
        setStatus("设置已保存在本机。新考试将使用这些规则。");
      } else {
        const data = await send<{ ok: boolean; message: string }>(
          "/settings/test",
          payload(),
        );
        setStatus(`${data.message}（测试未保存当前配置）`);
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }
  if (loaded.loading && !form) return <Loading />;
  return (
    <>
      <PageHeader
        eyebrow="让工具适合你的学习方式"
        title="设置"
        description="管理本地服务，连接自己的模型，定义评分方式和错误类型。"
      />
      <LocalService />
      <ErrorBox
        error={error || loaded.error || providers.error}
        onRetry={
          error
            ? undefined
            : () => {
                loaded.reload();
                providers.reload();
              }
        }
      />
      {status && <Status>{status}</Status>}
      {form && (
        <div className="settings-layout">
          <form
            ref={formRef}
            className="settings-main"
            onSubmit={(e) => {
              e.preventDefault();
              act("save");
            }}
          >
            <section className="panel settings-section">
              <div className="section-heading">
                <div className="section-title-icon">
                  <KeyRound size={22} aria-hidden="true" />
                  <h2>模型连接</h2>
                </div>
                <span className="section-index">01</span>
              </div>
              <p className="muted">
                卡片保存在本机；核对和评分时会把相关文本发送给你配置的模型服务。
              </p>
              <div className="form-grid">
                <label className="field">
                  提供商
                  <select
                    value={form.provider}
                    onChange={(e) => providerChanged(e.target.value)}
                  >
                    {providers.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  模型名称
                  <input
                    required
                    value={form.model}
                    onChange={(e) => change("model", e.target.value)}
                    placeholder="输入模型名称"
                  />
                </label>
              </div>
              <label className="field">
                接口地址
                <input
                  required
                  type="url"
                  value={form.base_url}
                  onChange={(e) => change("base_url", e.target.value)}
                />
              </label>
              <label className="field">
                API 密钥
                <span className="field-hint">
                  {form.has_api_key
                    ? "已保存密钥；留空保留现有密钥。"
                    : "尚未配置密钥。密钥仅保存在本机 SQLite 中。"}
                </span>
                <div className="key-input">
                  <input
                    autoComplete="off"
                    type={showKey ? "text" : "password"}
                    value={key}
                    placeholder={
                      form.has_api_key ? "••••••••（已保存）" : "输入 API 密钥"
                    }
                    onChange={(e) => {
                      setKey(e.target.value);
                      setClearKey(false);
                      setStatus("");
                    }}
                  />
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={showKey ? "隐藏密钥" : "显示密钥"}
                    onClick={() => setShowKey(!showKey)}
                  >
                    {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </label>
              {form.has_api_key && (
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={clearKey}
                    onChange={(e) => {
                      setClearKey(e.target.checked);
                      setKey("");
                    }}
                  />
                  保存时清除已存密钥
                </label>
              )}
              {loaded.data?.has_api_key &&
                (form.provider !== loaded.data.provider ||
                  form.base_url !== loaded.data.base_url) &&
                !key && (
                  <p className="notice warm">
                    连接地址或提供商已变化。请填写对应密钥；保存时会清除旧密钥。
                  </p>
                )}
              <div className="form-grid">
                <label className="field">
                  JSON 输出模式
                  <select
                    value={form.json_mode}
                    onChange={(e) =>
                      change(
                        "json_mode",
                        e.target.value as SettingsData["json_mode"],
                      )
                    }
                  >
                    <option value="auto">自动适配</option>
                    <option value="on">启用 JSON 模式</option>
                    <option value="off">仅提示词约束</option>
                  </select>
                </label>
                <label className="field">
                  单次请求超时（秒）
                  <input
                    required
                    type="number"
                    min="1"
                    max="600"
                    value={form.request_timeout}
                    onChange={(e) =>
                      change("request_timeout", Number(e.target.value))
                    }
                  />
                </label>
              </div>
              <button
                type="button"
                className="button"
                disabled={!!busy}
                onClick={() => act("test")}
              >
                <FlaskConical size={17} aria-hidden="true" />
                {busy === "test" ? "正在测试连接…" : "测试连接"}
              </button>
              <span className="field-hint inline-hint">
                使用当前填写的配置，不会自动保存。
              </span>
            </section>
            <section className="panel settings-section">
              <div className="section-heading">
                <div className="section-title-icon">
                  <SlidersHorizontal size={22} aria-hidden="true" />
                  <h2>评分规则</h2>
                </div>
                <span className="section-index">02</span>
              </div>
              <p className="muted">
                只依据你的参考定义评分。模型额外知识不计分，也不生成错误类型。
              </p>
              <div className="form-grid">
                <label className="field">
                  裁判数量
                  <select
                    value={form.judge_count}
                    onChange={(e) =>
                      change("judge_count", Number(e.target.value) as 2 | 3)
                    }
                  >
                    <option value="2">2 位裁判</option>
                    <option value="3">3 位裁判</option>
                  </select>
                </label>
                <label className="field">
                  及格线
                  <input
                    required
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={form.pass_threshold}
                    onChange={(e) =>
                      change("pass_threshold", Number(e.target.value))
                    }
                  />
                </label>
                <label className="field">
                  裁判温度
                  <input
                    required
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    value={form.judge_temperature}
                    onChange={(e) =>
                      change("judge_temperature", Number(e.target.value))
                    }
                  />
                </label>
                <label className="field">
                  合并温度
                  <input
                    required
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    value={form.merge_temperature}
                    onChange={(e) =>
                      change("merge_temperature", Number(e.target.value))
                    }
                  />
                </label>
              </div>
              <label className="field weight-label">
                评分权重
                <span className="field-hint">
                  正确率权重变化时，完整度权重自动补足至 100%。
                </span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  aria-label="正确率权重百分比"
                  value={Math.round(form.w_accuracy * 100)}
                  onChange={(e) => {
                    const weight = Number(e.target.value) / 100;
                    setForm({
                      ...form,
                      w_accuracy: weight,
                      w_completeness: 1 - weight,
                    });
                    setStatus("");
                  }}
                />
              </label>
              <div className="weight-values">
                <span>
                  正确率 <strong>{Math.round(form.w_accuracy * 100)}%</strong>
                </span>
                <span>
                  完整度{" "}
                  <strong>{Math.round(form.w_completeness * 100)}%</strong>
                </span>
              </div>
              <p className="formula">
                最终分数 = 正确率 × {Math.round(form.w_accuracy * 100)}% +
                完整度 × {Math.round(form.w_completeness * 100)}%
              </p>
            </section>
            <div className="settings-save">
              <span className="muted">已开始的考试保留当时的评分配置。</span>
              <button className="button primary" disabled={!!busy}>
                <Save size={17} aria-hidden="true" />
                {busy === "save" ? "正在保存…" : "保存设置"}
              </button>
            </div>
          </form>
          <aside className="settings-aside">
            <section className="panel">
              <div className="section-title-icon">
                <Tags size={21} aria-hidden="true" />
                <h2>错误类型</h2>
              </div>
              <p className="muted">
                AI 仅可从此列表选择。也可以在结果页手动修改每题标签。
              </p>
              <NamedManager path="/error-types" />
              <p className="field-hint">
                这里的改动立即保存。重命名或删除会同步历史记录中的标签。
              </p>
            </section>
            <div className="settings-note">
              <span className="eyebrow">评分透明，依据清楚</span>
              <p>多位裁判分别给分，成功结果取平均；评分失败不会记为零分。</p>
              <p>模型提示始终单独展示，供你参考。</p>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
