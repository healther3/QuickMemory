import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, BarChart3 } from "lucide-react";
import {
  duration,
  score,
  useLoad,
  type Folder,
  type Stats as StatsData,
  type Tag,
} from "../api";
import { Empty, ErrorBox, Loading, PageHeader, Stat } from "../ui";
export default function Stats() {
  const [params, setParams] = useSearchParams();
  const folders = useLoad<Folder[]>("/folders"),
    tags = useLoad<Tag[]>("/tags");
  const path = new URLSearchParams();
  if (params.get("folder_id")) path.set("folder_id", params.get("folder_id")!);
  if (params.get("tag_id")) path.set("tag_id", params.get("tag_id")!);
  const stats = useLoad<StatsData>(`/stats?${path}`);
  function filter(key: string, value: string) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      value ? next.set(key, value) : next.delete(key);
      return next;
    });
  }
  const max = Math.max(
    1,
    ...(stats.data?.error_distribution.map((e) => e.count) || []),
  );
  return (
    <>
      <PageHeader
        eyebrow="让每次练习留下轨迹"
        title="统计看板"
        description="回顾分数和作答记录，找到下一次复习的起点。"
      />
      <div className="toolbar stats-filters">
        <span className="muted">统计范围</span>
        <select
          aria-label="统计文件夹筛选"
          value={params.get("folder_id") || ""}
          onChange={(e) => filter("folder_id", e.target.value)}
        >
          <option value="">全部文件夹</option>
          {folders.data?.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <select
          aria-label="统计用户标签筛选"
          value={params.get("tag_id") || ""}
          onChange={(e) => filter("tag_id", e.target.value)}
        >
          <option value="">全部用户标签</option>
          {tags.data?.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>
      <ErrorBox
        error={stats.error || folders.error || tags.error}
        onRetry={() => {
          stats.reload();
          folders.reload();
          tags.reload();
        }}
      />
      {stats.loading && !stats.data ? (
        <Loading />
      ) : (
        stats.data && (
          <>
            <div className="stats-strip four panel">
              <Stat
                label="作答次数"
                value={stats.data.overview.attempt_count}
                detail={`${stats.data.overview.card_count} 张卡片`}
              />
              <Stat
                label="已评分均分"
                value={score(stats.data.overview.average_score)}
                detail={`基于 ${stats.data.overview.graded_count} 次成功评分`}
              />
              <Stat
                label="平均作答耗时"
                value={duration(stats.data.overview.average_time_ms)}
                detail="以已提交的作答计算"
              />
              <Stat
                label="文件夹"
                value={stats.data.overview.folder_count}
                detail="按当前统计范围"
              />
            </div>
            <section className="panel distribution">
              <div className="section-heading">
                <div>
                  <h2>错误类型分布</h2>
                  <p className="muted">
                    一次作答可有多个标签，数字表示被标记的次数。
                  </p>
                </div>
                <BarChart3 size={22} aria-hidden="true" />
              </div>
              {stats.data.error_distribution.some((e) => e.count) ? (
                <div
                  className="bar-chart"
                  role="img"
                  aria-label={stats.data.error_distribution
                    .map((e) => `${e.name} ${e.count} 次`)
                    .join("；")}
                >
                  {stats.data.error_distribution.map((item) => (
                    <div className="bar-row" key={item.id}>
                      <span>{item.name}</span>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{ width: `${(item.count / max) * 100}%` }}
                        />
                      </div>
                      <strong>
                        {item.count}
                        <small>次</small>
                      </strong>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="small-empty">
                  暂无错误类型记录。完成评分或手动标记后，会在这里显示。
                </div>
              )}
              <details className="data-disclosure">
                <summary>查看分布数据表</summary>
                <table>
                  <thead>
                    <tr>
                      <th>错误类型</th>
                      <th>标记次数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.data.error_distribution.map((item) => (
                      <tr key={item.id}>
                        <td>{item.name}</td>
                        <td>{item.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </section>
            <section>
              <div className="section-heading">
                <h2>卡片成绩</h2>
                <span className="muted">按平均分从低到高排列</span>
              </div>
              {stats.data.cards.length ? (
                <div className="table-wrap panel">
                  <table className="scores-table">
                    <thead>
                      <tr>
                        <th>概念</th>
                        <th>作答次数</th>
                        <th aria-sort="ascending">平均分 ↑</th>
                        <th>最低分</th>
                        <th>最近分数</th>
                        <th>平均耗时</th>
                        <th>
                          <span className="sr-only">历史</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.data.cards.map((card) => (
                        <tr key={card.id}>
                          <td data-label="概念">
                            <Link
                              className="term-link"
                              to={`/cards/${card.id}/history`}
                            >
                              {card.term}
                            </Link>
                          </td>
                          <td data-label="作答次数">{card.attempt_count}</td>
                          <td data-label="平均分">
                            <strong className="green-text">
                              {score(card.average_score)}
                            </strong>
                          </td>
                          <td data-label="最低分">
                            {score(card.lowest_score)}
                          </td>
                          <td data-label="最近分数">
                            {score(card.last_score)}
                          </td>
                          <td data-label="平均耗时">
                            {duration(card.average_time_ms)}
                          </td>
                          <td>
                            <Link
                              className="icon-button"
                              to={`/cards/${card.id}/history`}
                              aria-label={`查看${card.term}历史`}
                            >
                              <ArrowRight size={17} />
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty
                  title="还没有可统计的卡片"
                  description="试试其他筛选条件，或先添加一些概念。"
                />
              )}
            </section>
            <p className="quiet-note">
              未评分显示为“—”，不参与分数平均值计算。
            </p>
          </>
        )
      )}
    </>
  );
}
