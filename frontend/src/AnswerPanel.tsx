import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Clock3,
  RotateCcw,
} from "lucide-react";
import {
  date,
  duration,
  message,
  score,
  send,
  type Answer,
  type Named,
} from "./api";
import { ErrorBox, Pill, TextList } from "./ui";
export default function AnswerPanel({
  answer,
  types,
  onUpdate,
  defaultOpen = false,
}: {
  answer: Answer;
  types: Named[];
  onUpdate: (answer: Answer) => void;
  defaultOpen?: boolean;
}) {
  const [labels, setLabels] = useState(answer.error_types.map((t) => t.id)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [editing, setEditing] = useState(false);
  const labelSignature = answer.error_types.map((t) => t.id).join(",");
  useEffect(() => {
    if (!editing) setLabels(answer.error_types.map((t) => t.id));
  }, [labelSignature, editing]);
  async function save() {
    setBusy(true);
    setError("");
    try {
      onUpdate(
        await send<Answer>(
          `/answers/${answer.id}/error-types`,
          { error_type_ids: labels },
          "PATCH",
        ),
      );
      setEditing(false);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function retry() {
    setBusy(true);
    setError("");
    try {
      await send(`/answers/${answer.id}/retry-grade`);
      onUpdate({ ...answer, status: "pending", grading_error: null });
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="answer-panel panel" open={defaultOpen || undefined}>
      <summary className="answer-summary">
        <span className="answer-number">
          {String(answer.position + 1).padStart(2, "0")}
        </span>
        <div className="answer-title">
          <strong>{answer.term}</strong>
          <span>
            {date(answer.submitted_at || answer.created_at)} ·{" "}
            {duration(answer.time_spent_ms)}
          </span>
        </div>
        <Pill
          tone={
            answer.status === "graded"
              ? "green"
              : answer.status === "failed"
                ? "red"
                : "amber"
          }
        >
          {answer.status === "graded"
            ? "已评分"
            : answer.status === "failed"
              ? "未评分"
              : "正在评分"}
        </Pill>
        <strong className="answer-score">
          {score(answer.final_score)}
          <small>{answer.final_score === null ? "" : "分"}</small>
        </strong>
        <ChevronDown className="summary-chevron" size={19} aria-hidden="true" />
      </summary>
      <div className="answer-content">
        <div className="answer-metrics">
          <span>
            正确率 <strong>{score(answer.accuracy)}</strong>
          </span>
          <span>
            完整度 <strong>{score(answer.completeness)}</strong>
          </span>
          <span>
            <Clock3 size={15} aria-hidden="true" />
            作答耗时 <strong>{duration(answer.time_spent_ms)}</strong>
          </span>
        </div>
        <div className="comparison">
          <section>
            <h3>
              参考定义 <span>考试时的快照</span>
            </h3>
            <p className="plain-text">{answer.definition}</p>
          </section>
          <section>
            <h3>我的回答</h3>
            <p className="plain-text">{answer.user_answer || "（空白答案）"}</p>
          </section>
        </div>
        {answer.status === "pending" && (
          <div className="notice subtle" role="status">
            正在等待模型评分，结果会自动更新。
          </div>
        )}
        {answer.status === "failed" && (
          <div className="notice danger">
            <div>
              <strong>未评分</strong>
              <p>
                {answer.grading_error ||
                  "所有裁判均未能完成评分，请检查模型连接后重试。"}
              </p>
            </div>
            <button className="button small" disabled={busy} onClick={retry}>
              <RotateCcw size={16} aria-hidden="true" />
              重新评分
            </button>
          </div>
        )}
        {answer.status === "graded" && answer.merged_feedback && (
          <div className="feedback-grid">
            <section>
              <h3>
                <span className="feedback-dot green" />
                正确的部分
              </h3>
              <TextList
                items={answer.merged_feedback.correct_parts ?? []}
                empty="未指出正确的部分"
              />
            </section>
            <section>
              <h3>
                <span className="feedback-dot red" />
                错误的部分
              </h3>
              <TextList
                items={answer.merged_feedback.wrong_parts ?? []}
                empty="未发现与参考定义矛盾的内容"
              />
            </section>
            <section>
              <h3>
                <span className="feedback-dot neutral" />
                不确定的部分
              </h3>
              <TextList
                items={answer.merged_feedback.uncertain_parts ?? []}
                empty="无不确定的部分"
              />
            </section>
          </div>
        )}
        {answer.model_knowledge_notes?.length > 0 && (
          <section className="knowledge-notes">
            <h3>模型提示（不计分，仅供参考）</h3>
            <TextList items={answer.model_knowledge_notes} />
          </section>
        )}
        {answer.status === "graded" && (
          <section className="answer-labels">
            <div className="section-heading">
              <h3>错误类型</h3>
              <button
                className="text-button"
                onClick={() => setEditing(!editing)}
              >
                {editing ? "取消修改" : "修改标签"}
              </button>
            </div>
            {editing ? (
              <>
                <div className="checkbox-group">
                  {types.map((type) => (
                    <label className="checkbox" key={type.id}>
                      <input
                        type="checkbox"
                        checked={labels.includes(type.id)}
                        onChange={(e) =>
                          setLabels(
                            e.target.checked
                              ? [...labels, type.id]
                              : labels.filter((i) => i !== type.id),
                          )
                        }
                      />
                      {type.name}
                    </label>
                  ))}
                </div>
                <button className="button small" disabled={busy} onClick={save}>
                  <Check size={15} aria-hidden="true" />
                  保存标签
                </button>
              </>
            ) : (
              <div className="pills">
                {answer.error_types.length ? (
                  answer.error_types.map((type) => (
                    <Pill key={type.id}>{type.name}</Pill>
                  ))
                ) : (
                  <span className="muted">未标记错误类型</span>
                )}
              </div>
            )}
          </section>
        )}
        <ErrorBox error={error} />
        {answer.disagreement && (
          <div className="notice warm">
            <AlertTriangle size={18} aria-hidden="true" />
            裁判评分差异较大：至少一个评分维度相差超过 20 分。
          </div>
        )}
        {answer.merge_fallback && (
          <div className="notice warm">
            反馈合并未成功，当前文字采用第一位成功裁判的反馈；分数仍为成功裁判的平均值。
          </div>
        )}
        {answer.judges?.length > 0 && (
          <details className="judge-details">
            <summary>
              查看裁判详情 · {answer.judges.filter((j) => j.success).length}/
              {answer.judges.length} 位成功
            </summary>
            <div className="judge-grid">
              {answer.judges.map((judge) => (
                <div key={judge.judge_index} className="judge">
                  <h4>
                    裁判 {judge.judge_index}{" "}
                    <Pill tone={judge.success ? "green" : "red"}>
                      {judge.success ? "成功" : "失败"}
                    </Pill>
                  </h4>
                  <p>
                    正确率 {score(judge.accuracy)} · 完整度{" "}
                    {score(judge.completeness)}
                  </p>
                  {judge.error && <p className="danger-text">{judge.error}</p>}
                  <details>
                    <summary>查看原始输出</summary>
                    <pre>
                      {judge.raw_json
                        ? JSON.stringify(judge.raw_json, null, 2)
                        : judge.raw_text || "没有原始输出"}
                    </pre>
                  </details>
                </div>
              ))}
            </div>
            <p className="field-hint">
              模型：{answer.model_name || "未记录"} · 提示词版本：
              {answer.prompt_version || "未记录"}
            </p>
          </details>
        )}
      </div>
    </details>
  );
}
