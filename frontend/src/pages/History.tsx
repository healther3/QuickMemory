import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { Pencil } from "lucide-react";
import {
  date,
  duration,
  score,
  useLoad,
  type Answer,
  type CardHistory,
  type Named,
} from "../api";
import AnswerPanel from "../AnswerPanel";
import { Back, Empty, ErrorBox, Loading, PageHeader, Stat } from "../ui";
export default function History() {
  const { id } = useParams();
  const location = useLocation();
  const returnTo =
    typeof location.state?.returnTo === "string" &&
    location.state.returnTo.startsWith("/cards")
      ? location.state.returnTo
      : "/cards";
  const history = useLoad<CardHistory>(`/cards/${id}/history`),
    types = useLoad<Named[]>("/error-types");
  const pending = history.data?.answers.some((a) => a.status === "pending");
  useEffect(() => {
    if (!pending || history.loading || history.error) return;
    const timer = setTimeout(history.reload, 2000);
    return () => clearTimeout(timer);
  }, [pending, history.data, history.loading, history.error, history.reload]);
  function update(answer: Answer) {
    history.setData((data) =>
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
      <Back to={returnTo} />
      <PageHeader
        eyebrow="一张卡片的记忆轨迹"
        title={history.data?.card.term || "作答历史"}
        description="每次回答都保留当时的参考定义、评分与模型提示。"
        actions={
          <Link
            className="button"
            to={`/cards/${id}/edit`}
            state={{ returnTo }}
          >
            <Pencil size={16} aria-hidden="true" />
            编辑卡片
          </Link>
        }
      />
      <ErrorBox
        error={history.error || types.error}
        onRetry={() => {
          history.reload();
          types.reload();
        }}
      />
      {history.loading && !history.data ? (
        <Loading />
      ) : (
        history.data && (
          <>
            <div className="stats-strip five panel">
              <Stat label="作答次数" value={history.data.stats.attempt_count} />
              <Stat
                label="平均分"
                value={score(history.data.stats.average_score)}
              />
              <Stat
                label="最低分"
                value={score(history.data.stats.lowest_score)}
              />
              <Stat
                label="最近分数"
                value={score(history.data.stats.last_score)}
              />
              <Stat
                label="平均耗时"
                value={duration(history.data.stats.average_time_ms)}
              />
            </div>
            {history.data.answers.length ? (
              <>
                <section className="panel history-chart">
                  <div className="section-heading">
                    <h2>分数历史</h2>
                    <span className="muted">
                      纵轴 0–100 分 · 未评分保留缺口
                    </span>
                  </div>
                  <HistoryChart answers={history.data.answers} />
                </section>
                <div className="section-heading">
                  <h2>历次作答</h2>
                  <span className="muted">
                    共 {history.data.answers.length} 次
                  </span>
                </div>
                <div className="answer-stack">
                  {history.data.answers.map((answer, index) => (
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
            ) : (
              <Empty
                title="还没有考试记录"
                description="从卡片所在文件夹开始一次默写，让这里留下你的第一条记录。"
                action={
                  <Link className="button primary" to="/folders">
                    前往文件夹
                  </Link>
                }
              />
            )}
          </>
        )
      )}
    </>
  );
}
function HistoryChart({ answers }: { answers: Answer[] }) {
  const rows = [...answers].sort(
    (a, b) =>
      new Date(a.submitted_at || a.created_at).getTime() -
      new Date(b.submitted_at || b.created_at).getTime(),
  );
  const x = (i: number) =>
    rows.length === 1 ? 320 : 48 + (i / (rows.length - 1)) * 550;
  const y = (value: number) => 194 - value * 1.6;
  const segments: string[] = [];
  let segment = "";
  rows.forEach((answer, index) => {
    if (answer.final_score == null) {
      if (segment) segments.push(segment);
      segment = "";
    } else segment += `${x(index)},${y(answer.final_score)} `;
  });
  if (segment) segments.push(segment);
  return (
    <>
      <svg
        viewBox="0 0 640 240"
        role="img"
        aria-label="历次考试分数变化，下方数据表提供完整数值。"
      >
        {[0, 25, 50, 75, 100].map((value) => (
          <g key={value}>
            <line
              className="chart-grid-line"
              x1="48"
              x2="612"
              y1={y(value)}
              y2={y(value)}
            />
            <text x="26" y={y(value) + 5} textAnchor="middle">
              {value}
            </text>
          </g>
        ))}
        {segments.map((points, index) => (
          <polyline className="score-line" key={index} points={points} />
        ))}
        {rows.map((answer, index) =>
          answer.final_score === null ? null : (
            <g key={answer.id}>
              <circle
                className="score-point"
                cx={x(index)}
                cy={y(answer.final_score)}
                r="4.5"
              >
                <title>
                  {date(answer.submitted_at || answer.created_at)}：
                  {score(answer.final_score)} 分
                </title>
              </circle>
              {rows.length <= 12 && (
                <text
                  x={x(index)}
                  y={y(answer.final_score) - 12}
                  textAnchor="middle"
                >
                  {score(answer.final_score)}
                </text>
              )}
            </g>
          ),
        )}
        <text x="48" y="229">
          {date(rows[0].submitted_at || rows[0].created_at)}
        </text>
        {rows.length > 1 && (
          <text x="605" y="229" textAnchor="end">
            {date(
              rows[rows.length - 1].submitted_at ||
                rows[rows.length - 1].created_at,
            )}
          </text>
        )}
      </svg>
      <details className="data-disclosure">
        <summary>查看分数数据表</summary>
        <table>
          <thead>
            <tr>
              <th>作答时间</th>
              <th>分数</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((answer) => (
              <tr key={answer.id}>
                <td>{date(answer.submitted_at || answer.created_at)}</td>
                <td>{score(answer.final_score)}</td>
                <td>
                  {answer.status === "graded"
                    ? "已评分"
                    : answer.status === "failed"
                      ? "未评分"
                      : "正在评分"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}
