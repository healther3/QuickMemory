import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Download,
  FolderOpen,
  Pencil,
  Play,
  Plus,
  Trash2,
  Upload,
} from "lucide-react";
import {
  api,
  date,
  message,
  send,
  useLoad,
  type Exam,
  type Folder,
} from "../api";
import { Empty, ErrorBox, Loading, Modal, PageHeader, Pill } from "../ui";
export default function Folders() {
  const folders = useLoad<Folder[]>("/folders");
  const exams = useLoad<{ items: Exam[]; total: number }>("/exams?limit=10");
  const navigate = useNavigate();
  const [editing, setEditing] = useState<Folder | "new" | null>(null),
    [name, setName] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [starting, setStarting] = useState<number | null>(null);
  async function save() {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await send(
        editing === "new" ? "/folders" : `/folders/${editing?.id}`,
        { name: name.trim() },
        editing === "new" ? "POST" : "PUT",
      );
      setEditing(null);
      folders.reload();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function remove(folder: Folder) {
    if (
      !window.confirm(`删除文件夹「${folder.name}」？卡片和历史考试仍会保留。`)
    )
      return;
    setError("");
    try {
      await api(`/folders/${folder.id}`, { method: "DELETE" });
      folders.reload();
    } catch (e) {
      setError(message(e));
    }
  }
  async function start(folder: Folder) {
    setStarting(folder.id);
    setError("");
    try {
      const exam = await send<Exam>("/exams", { folder_id: folder.id });
      navigate(`/exams/${exam.id}`);
    } catch (e) {
      setError(message(e));
    } finally {
      setStarting(null);
    }
  }
  return (
    <>
      <PageHeader
        eyebrow="为下一次回想做好准备"
        title="学习文件夹"
        description="把相关的概念放在一起，以你自己的节奏开始默写。"
        actions={
          <button
            className="button primary"
            onClick={() => {
              setEditing("new");
              setName("");
              setError("");
            }}
          >
            <Plus size={18} aria-hidden="true" />
            新建文件夹
          </button>
        }
      />
      {!editing && (
        <ErrorBox error={error || folders.error} onRetry={folders.reload} />
      )}
      <div className="notice subtle">
        <FolderOpen size={20} aria-hidden="true" />
        <div>
          每次考试使用文件夹中的全部卡片，顺序随机，无时间限制。
          <span className="field-hint">同一卡片可以放入多个文件夹。</span>
        </div>
      </div>
      {folders.loading && !folders.data ? (
        <Loading />
      ) : folders.data?.length ? (
        <div className="folder-grid">
          {folders.data.map((folder, index) => (
            <article className="panel folder-card" key={folder.id}>
              <div className="folder-card-top">
                <span className="folder-symbol">
                  <FolderOpen size={29} strokeWidth={1.4} aria-hidden="true" />
                </span>
                <span className="folder-number">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <button
                  className="icon-button"
                  aria-label={`重命名${folder.name}`}
                  onClick={() => {
                    setEditing(folder);
                    setName(folder.name);
                    setError("");
                  }}
                >
                  <Pencil size={16} />
                </button>
                <button
                  className="icon-button danger-text"
                  aria-label={`删除${folder.name}`}
                  onClick={() => remove(folder)}
                >
                  <Trash2 size={16} />
                </button>
              </div>
              <h2>
                <Link to={`/cards?folder_id=${folder.id}`}>{folder.name}</Link>
              </h2>
              <p>
                <strong>{folder.card_count}</strong> 张概念卡片
              </p>
              <div className="folder-card-actions">
                <Link
                  to={`/cards?folder_id=${folder.id}`}
                  className="text-button"
                >
                  查看卡片 <ArrowRight size={16} aria-hidden="true" />
                </Link>
                <div className="actions">
                  <Link
                    className="icon-button"
                    to={`/import?folder_id=${folder.id}`}
                    aria-label={`向${folder.name}导入题库`}
                  >
                    <Upload size={17} />
                  </Link>
                  <a
                    className="icon-button"
                    href={`/api/folders/${folder.id}/export`}
                    download
                    aria-label={`导出${folder.name}为JSON备份`}
                  >
                    <Download size={17} />
                  </a>
                </div>
              </div>
              <button
                className="button primary full"
                disabled={!folder.card_count || starting !== null}
                onClick={() => start(folder)}
              >
                <Play size={16} aria-hidden="true" />
                {starting === folder.id
                  ? "正在准备…"
                  : folder.card_count
                    ? "开始考试"
                    : "先添加卡片"}
              </button>
            </article>
          ))}
        </div>
      ) : (
        <Empty
          title="还没有文件夹"
          description="创建一个主题文件夹，整理卡片并开始考试。"
          action={
            <button
              className="button primary"
              onClick={() => {
                setEditing("new");
                setName("");
              }}
            >
              新建文件夹
            </button>
          }
        />
      )}
      <section className="recent-section">
        <div className="section-heading">
          <h2>最近的考试</h2>
          <span className="muted">继续作答，或回顾结果</span>
        </div>
        <ErrorBox error={exams.error} onRetry={exams.reload} />
        {exams.data?.items.length ? (
          <div className="panel exam-list">
            {exams.data.items.map((exam) => (
              <Link
                className="exam-list-row"
                key={exam.id}
                to={`/exams/${exam.id}${exam.finished_at ? "/results" : ""}`}
              >
                <span className="exam-list-icon">
                  <BookMark />
                </span>
                <div>
                  <strong>{exam.folder_name}</strong>
                  <span>
                    {date(exam.started_at)} · {exam.total} 道题
                  </span>
                </div>
                <Pill tone={exam.finished_at ? "green" : "amber"}>
                  {exam.finished_at
                    ? "已完成作答"
                    : `已提交 ${exam.submitted_count}/${exam.total}`}
                </Pill>
                <ArrowRight size={18} aria-hidden="true" />
              </Link>
            ))}
          </div>
        ) : (
          <div className="small-empty">
            完成一次默写后，你的考试记录会出现在这里。
          </div>
        )}
      </section>
      {editing && (
        <Modal
          title={editing === "new" ? "新建文件夹" : "重命名文件夹"}
          onClose={() => setEditing(null)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
          >
            <ErrorBox error={error} />
            <label className="field">
              文件夹名称
              <input
                autoFocus
                required
                maxLength={200}
                value={name}
                placeholder="例如：机器学习基础"
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <div className="actions end">
              <button
                type="button"
                className="button"
                onClick={() => setEditing(null)}
              >
                取消
              </button>
              <button
                className="button primary"
                disabled={busy || !name.trim()}
              >
                {busy ? "正在保存…" : "保存"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
function BookMark() {
  return <Pencil size={19} strokeWidth={1.5} aria-hidden="true" />;
}
