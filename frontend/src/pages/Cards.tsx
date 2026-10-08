import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  Layers3,
  Plus,
  Search,
  SlidersHorizontal,
  Tags,
  Upload,
} from "lucide-react";
import { useLoad, type Card, type Folder, type Tag } from "../api";
import { Empty, ErrorBox, Loading, Modal, PageHeader, Pill } from "../ui";
import NamedManager from "../NamedManager";
export default function Cards() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") || "");
  const [manage, setManage] = useState(false);
  const folders = useLoad<Folder[]>("/folders"),
    tags = useLoad<Tag[]>("/tags");
  const page = Math.max(1, Number(params.get("page")) || 1);
  const folder = params.get("folder_id") || "",
    tag = params.get("tag_id") || "",
    q = params.get("q") || "";
  useEffect(() => {
    setQuery(q);
  }, [q]);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (query !== q) {
        setParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            query ? next.set("q", query) : next.delete("q");
            next.delete("page");
            return next;
          },
          { replace: true },
        );
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query, q, setParams]);
  const cards = useLoad<{ items: Card[]; total: number }>(
    `/cards?${new URLSearchParams({ q, folder_id: folder, tag_id: tag, offset: String((page - 1) * 12), limit: "12" }).toString().replace(/(?:folder_id|tag_id)=&?/g, "")}`,
  );
  const returnTo = `/cards${params.toString() ? `?${params}` : ""}`;
  const scrollRestored = useRef(false);
  useEffect(() => {
    if (cards.loading || !cards.data || scrollRestored.current) return;
    scrollRestored.current = true;
    try {
      const saved = JSON.parse(
        sessionStorage.getItem("qm-library-position") || "null",
      );
      if (saved?.path === returnTo) window.scrollTo(0, saved.y);
    } catch {
      /* Scrolling remains available when browser storage is disabled. */
    }
  }, [cards.loading, cards.data, returnTo]);
  function rememberPosition() {
    try {
      sessionStorage.setItem(
        "qm-library-position",
        JSON.stringify({ path: returnTo, y: window.scrollY }),
      );
    } catch {
      /* Optional navigation convenience. */
    }
  }
  function filter(key: string, value: string) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      value ? next.set(key, value) : next.delete(key);
      if (key !== "page") next.delete("page");
      return next;
    });
  }
  const folderName = folders.data?.find((f) => String(f.id) === folder)?.name;
  return (
    <>
      <PageHeader
        eyebrow="知识从这里开始"
        title={folderName || "我的卡片"}
        description="写下你的理解，在一次次回想中，让概念更清晰。"
        actions={
          <>
            <Link
              className="button"
              to={`/import${folder ? `?folder_id=${folder}` : ""}`}
            >
              <Upload size={17} aria-hidden="true" />
              导入题库
            </Link>
            <Link
              className="button primary"
              to={`/cards/new${folder ? `?folder_id=${folder}` : ""}`}
              state={{ returnTo }}
              onClick={rememberPosition}
            >
              <Plus size={19} aria-hidden="true" />
              新建卡片
            </Link>
          </>
        }
      />
      <div className="library-overview">
        <div>
          <span className="overview-icon">
            <Layers3 size={23} strokeWidth={1.5} aria-hidden="true" />
          </span>
          <div>
            <strong>{cards.data?.total ?? "—"}</strong>
            <span>{q || folder || tag ? "符合条件的卡片" : "张概念卡片"}</span>
          </div>
        </div>
        <div>
          <span className="overview-icon">
            <FolderOpen size={23} strokeWidth={1.5} aria-hidden="true" />
          </span>
          <div>
            <strong>{folders.data?.length ?? "—"}</strong>
            <span>个学习文件夹</span>
          </div>
        </div>
        <div className="overview-tip">
          <span className="eyebrow">从理解到记忆</span>
          <p>
            整理概念，选择一个文件夹，
            <br />
            开始你的下一次默写。
          </p>
          <Link to="/folders">
            前往文件夹 <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </div>
      <div className="section-heading library-heading">
        <h2>
          概念库 <span className="count">{cards.data?.total ?? "—"}</span>
        </h2>
        <button className="text-button" onClick={() => setManage(true)}>
          <Tags size={16} aria-hidden="true" />
          管理标签
        </button>
      </div>
      <div className="toolbar">
        <label className="search">
          <Search size={19} aria-hidden="true" />
          <input
            aria-label="搜索术语或定义"
            placeholder="搜索术语或定义…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <label className="select-label">
          <SlidersHorizontal size={16} aria-hidden="true" />
          <select
            aria-label="按用户标签筛选"
            value={tag}
            onChange={(e) => filter("tag_id", e.target.value)}
          >
            <option value="">全部标签</option>
            {tags.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <select
          aria-label="按文件夹筛选"
          value={folder}
          onChange={(e) => filter("folder_id", e.target.value)}
        >
          <option value="">全部文件夹</option>
          {folders.data?.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        {(q || folder || tag) && (
          <button
            className="text-button"
            onClick={() => {
              setParams({});
              setQuery("");
            }}
          >
            清除筛选
          </button>
        )}
      </div>
      <ErrorBox
        error={cards.error || folders.error || tags.error}
        onRetry={() => {
          cards.reload();
          folders.reload();
          tags.reload();
        }}
      />
      {cards.loading && !cards.data ? (
        <Loading />
      ) : cards.data?.items.length ? (
        <>
          <div className="card-list">
            <div className="card-list-head">
              <span>术语与定义</span>
              <span>分类与文件夹</span>
              <span>查看</span>
            </div>
            {cards.data.items.map((card, index) => (
              <article className="library-card" key={card.id}>
                <span className="card-index">
                  {String((page - 1) * 12 + index + 1).padStart(2, "0")}
                </span>
                <div className="card-copy">
                  <Link
                    className="term-link"
                    to={`/cards/${card.id}/edit`}
                    state={{ returnTo }}
                    onClick={rememberPosition}
                  >
                    {card.term}
                  </Link>
                  <p>{card.definition}</p>
                </div>
                <div className="card-taxonomy">
                  <div className="pills">
                    {card.tags.map((t) => (
                      <Pill key={t.id}>{t.name}</Pill>
                    ))}
                    {!card.tags.length && (
                      <span className="muted">未设置标签</span>
                    )}
                  </div>
                  <div className="folder-names">
                    <FolderOpen size={14} aria-hidden="true" />
                    {card.folders.map((f) => f.name).join(" · ") ||
                      "未归入文件夹"}
                  </div>
                </div>
                <Link
                  className="icon-button card-open"
                  to={`/cards/${card.id}/edit`}
                  state={{ returnTo }}
                  onClick={rememberPosition}
                  aria-label={`编辑${card.term}`}
                >
                  <ArrowRight size={19} />
                </Link>
              </article>
            ))}
          </div>
          <div className="pagination">
            <span>
              第 {Math.min((page - 1) * 12 + 1, cards.data.total)}–
              {Math.min(page * 12, cards.data.total)} 张，共 {cards.data.total}{" "}
              张
            </span>
            <div className="actions">
              <button
                className="icon-button"
                aria-label="上一页"
                disabled={page === 1}
                onClick={() => filter("page", String(page - 1))}
              >
                <ChevronLeft size={18} />
              </button>
              <span>
                {page} / {Math.max(1, Math.ceil(cards.data.total / 12))}
              </span>
              <button
                className="icon-button"
                aria-label="下一页"
                disabled={page * 12 >= cards.data.total}
                onClick={() => filter("page", String(page + 1))}
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        </>
      ) : (
        <Empty
          title={q || folder || tag ? "没有符合条件的卡片" : "还没有卡片"}
          description="把一个想记住的概念写下来，学习就从这里开始。"
          action={
            <Link className="button primary" to="/cards/new">
              <Plus size={18} aria-hidden="true" />
              新建卡片
            </Link>
          }
        />
      )}
      <div className="quiet-note">
        <span className="dot" />
        参考定义由你书写，也是考试评分的唯一标准。
      </div>
      {manage && (
        <Modal title="管理用户标签" onClose={() => setManage(false)}>
          <p className="muted">
            用于整理和搜索卡片，与考试的错误类型相互独立。
          </p>
          <NamedManager
            path="/tags"
            onChange={() => {
              tags.reload();
              cards.reload();
            }}
          />
        </Modal>
      )}
    </>
  );
}
