import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { RotateCcw } from "lucide-react";
import {
  message,
  score,
  send,
  useLoad,
  type Answer,
  type Exam,
  type Named,
} from "../api";
import { Back, ErrorBox, Loading, PageHeader, Stat } from "../ui";
import AnswerPanel from "../AnswerPanel";
export default function Results() {
  const { id } = useParams();
  const results = useLoad<Exam<Answer>>(`/exams/${id}/results`);
  const types = useLoad<Named[]>("/error-types");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const navigate = useNavigate();
  const pending =
    results.data?.answers.filter((a) => a.status === "pending").length ?? 0;
  useEffect(() => {
    if (!pending || results.loading || results.error) return;
    const timer = setTimeout(results.reload, 2000);
    return () => clearTimeout(timer);
  }, [pending, results.data, results.loading, results.error, results.reload]);
  const graded =
      results.data?.answers.filter((a) => a.status === "graded") ?? [],
    wrong = graded.filter((a) => a.final_score! < results.data!.pass_threshold);
  const average = graded.length
    ? graded.reduce((n, a) => n + a.final_score!, 0) / graded.length
    : null;
  async function retry() {
    setBusy(true);
    setError("");
    try {
      const next = await send<Exam>(`/exams/${id}/retry`);
      navigate(`/exams/${next.id}`);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  function update(answer: Answer) {
    results.setData((data) =>
      data
        ? {
            ...data,
            answers: data.answers.map((a) => (a.id === answer.id ? answer : a)),
          }
        : data,
    );
  }
  return (
    <>
      <Back to="/folders">返回文件夹</Back>
      <PageHeader
        eyebrow="每一次回顾，都有新的发现"
        title="考试结果"
        description={
          results.data
            ? `${results.data.folder_name} · 共 ${results.data.total} 题 · 及格线 ${results.data.pass_threshold} 分`
            : "正在读取这次考试的结果。"
        }
        actions={
          <button
            className="button primary"
            disabled={busy || !!pending || !wrong.length}
            onClick={retry}
          >
            <RotateCcw size={17} aria-hidden="true" />
            {busy
              ? "正在准备…"
              : `只重考错题${wrong.length ? `（${wrong.length}）` : ""}`}
          </button>
        }
      />
      <ErrorBox
        error={error || results.error || types.error}
        onRetry={() => {
          results.reload();
          types.reload();
        }}
      />
      {results.error && (
        <Link className="text-button" to={`/exams/${id}`}>
          返回考试继续作答
        </Link>
      )}
      {results.loading && !results.data ? (
        <Loading />
      ) : (
        results.data && (
          <>
            <div className="stats-strip four panel result-stats">
              <Stat
                label={pending ? "当前平均分" : "已评分平均分"}
                value={score(average)}
                detail={`仅计算 ${graded.length} 道已评分题目`}
              />
              <Stat
                label="已完成评分"
                value={graded.length}
                detail={`共 ${results.data.total} 道题`}
              />
              <Stat
                label="等待评分"
                value={pending}
                detail={pending ? "结果自动更新" : "全部后台任务已结束"}
              />
              <Stat
                label="未评分"
                value={
                  results.data.answers.filter((a) => a.status === "failed")
                    .length
                }
                detail="失败结果不记为零分"
              />
            </div>
            <div className="result-context">
              <span>唯一评分标准：你写下的参考定义。</span>
              <span role="status">
                {pending
                  ? `还有 ${pending} 题正在评分`
                  : wrong.length
                    ? `${wrong.length} 题低于及格线，可单独重考`
                    : "没有低于及格线的已评分题目"}
              </span>
            </div>
            <div className="answer-stack">
              {results.data.answers.map((answer, index) => (
                <AnswerPanel
                  key={answer.id}
                  answer={answer}
                  types={types.data ?? []}
                  onUpdate={update}
                  defaultOpen={index === 0}
                />
              ))}
            </div>
          </>
        )
      )}
    </>
  );
}
