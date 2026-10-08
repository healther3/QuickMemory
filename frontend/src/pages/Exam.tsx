import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Clock3, LockKeyhole } from "lucide-react";
import {
  ApiError,
  message,
  send,
  useLoad,
  type Exam as ExamData,
  type Question,
} from "../api";
import { ErrorBox, Loading, PageHeader } from "../ui";

export default function Exam() {
  const { id } = useParams();
  const exam = useLoad<ExamData>(`/exams/${id}`);
  const navigate = useNavigate();
  const question = exam.data?.answers.find((a) => !a.submitted_at);
  useEffect(() => {
    if (exam.data && !question)
      navigate(`/exams/${id}/results`, { replace: true });
  }, [exam.data, question, navigate, id]);
  function submitted() {
    if (!exam.data || !question) return;
    const answers = exam.data.answers.map((a) =>
      a.id === question.id
        ? { ...a, submitted_at: new Date().toISOString() }
        : a,
    );
    exam.setData({
      ...exam.data,
      answers,
      submitted_count: exam.data.submitted_count + 1,
    });
  }
  if (exam.loading && !exam.data) return <Loading text="正在准备题目…" />;
  return (
    <>
      <ErrorBox error={exam.error} onRetry={exam.reload} />
      {exam.data && question && (
        <>
          <PageHeader
            eyebrow="专注这一刻的回想"
            title={exam.data.folder_name}
            description="只需写下你记得的内容。没有时间限制，不必急着作答。"
            actions={
              <Link className="button" to="/folders">
                暂时离开
              </Link>
            }
          />
          <div className="exam-progress-heading">
            <span>
              第 <strong>{question.position + 1}</strong> / {exam.data.total} 题
            </span>
            <span>
              {exam.data.submitted_count} 题已提交 · 后台评分不影响作答
            </span>
          </div>
          <progress
            className="exam-progress"
            value={exam.data.submitted_count}
            max={exam.data.total}
            aria-label="作答进度"
          />
          <QuestionForm
            key={question.id}
            question={question}
            last={exam.data.submitted_count + 1 === exam.data.total}
            onSubmitted={submitted}
            onReconcile={exam.reload}
          />
        </>
      )}
    </>
  );
}

type Submission = { user_answer: string; time_spent_ms: number };
type Draft = { text: string; elapsed: number; submission: Submission | null };
function readDraft(id: number): Draft {
  try {
    const value = JSON.parse(localStorage.getItem(`qm-answer-${id}`) || "null");
    if (
      value &&
      typeof value.text === "string" &&
      typeof value.elapsed === "number"
    )
      return {
        text: value.text,
        elapsed: value.elapsed,
        submission:
          value.submission &&
          typeof value.submission.user_answer === "string" &&
          typeof value.submission.time_spent_ms === "number"
            ? value.submission
            : null,
      };
  } catch {
    /* Unavailable storage falls back to in-memory state. */
  }
  return { text: "", elapsed: 0, submission: null };
}
function writeDraft(id: number, draft: Draft): boolean {
  try {
    localStorage.setItem(`qm-answer-${id}`, JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
}
function QuestionForm({
  question,
  last,
  onSubmitted,
  onReconcile,
}: {
  question: Question;
  last: boolean;
  onSubmitted: () => void;
  onReconcile: () => void;
}) {
  const draft = useRef(readDraft(question.id));
  const [answer, setAnswer] = useState(draft.current.text),
    [elapsed, setElapsed] = useState(draft.current.elapsed),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [storageFailed, setStorageFailed] = useState(false),
    [locked, setLocked] = useState(!!draft.current.submission);
  const start = useRef(performance.now()),
    input = useRef<HTMLTextAreaElement>(null),
    content = useRef(answer),
    submission = useRef(draft.current.submission);
  content.current = answer;
  const getTime = () =>
    submission.current?.time_spent_ms ??
    Math.round(draft.current.elapsed + performance.now() - start.current);
  useEffect(() => {
    input.current?.focus();
    const timer = setInterval(() => {
      const time = getTime();
      setElapsed(time);
      setStorageFailed(
        !writeDraft(question.id, {
          text: content.current,
          elapsed: time,
          submission: submission.current,
        }),
      );
    }, 1000);
    return () => clearInterval(timer);
  }, [question.id]);
  useEffect(() => {
    setStorageFailed(
      !writeDraft(question.id, {
        text: answer,
        elapsed,
        submission: submission.current,
      }),
    );
  }, [answer, elapsed, question.id]);
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => {
      writeDraft(question.id, {
        text: content.current,
        elapsed: getTime(),
        submission: submission.current,
      });
      if (content.current.trim()) event.preventDefault();
    };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [question.id]);
  useEffect(() => {
    if (!storageFailed) return;
    const guard = (event: MouseEvent) => {
      const link = (event.target as Element).closest("a");
      if (
        link &&
        content.current.trim() &&
        !window.confirm(
          "浏览器无法保存草稿。确认离开并放弃本题尚未提交的内容？",
        )
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("click", guard, true);
    return () => document.removeEventListener("click", guard, true);
  }, [storageFailed]);
  async function submit() {
    if (
      !submission.current &&
      !answer.trim() &&
      !window.confirm("本题尚未填写答案，确认提交空白答案？")
    )
      return;
    // Retain the exact text and time for retries, including after refresh.
    if (!submission.current)
      submission.current = { user_answer: answer, time_spent_ms: getTime() };
    writeDraft(question.id, {
      text: answer,
      elapsed: submission.current.time_spent_ms,
      submission: submission.current,
    });
    setLocked(true);
    setBusy(true);
    setError("");
    try {
      await send(`/answers/${question.id}/submit`, submission.current);
      try {
        localStorage.removeItem(`qm-answer-${question.id}`);
      } catch {
        /* Already persisted by the server. */
      }
      onSubmitted();
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500
      ) {
        if (error.status === 409) onReconcile();
        else {
          submission.current = null;
          setLocked(false);
        }
      }
      setError(message(error));
      setBusy(false);
    }
  }
  return (
    <section className="exam-sheet panel">
      <div className="exam-sheet-top">
        <span className="eyebrow">请解释下面的概念</span>
        <span className="timer">
          <Clock3 size={16} aria-hidden="true" />
          {String(Math.floor(elapsed / 60000)).padStart(2, "0")}:
          {String(Math.floor(elapsed / 1000) % 60).padStart(2, "0")}
        </span>
      </div>
      <h2 className="exam-term">{question.term}</h2>
      <div className="exam-rule" />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className="field">
          你的回答
          <textarea
            ref={input}
            rows={10}
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder="试着用自己的语言写下定义和关键要点…"
            disabled={busy || locked}
          />
        </label>
        <ErrorBox error={error} />
        {locked && !busy && (
          <p className="field-hint">
            上次提交尚未确认。再次点击将安全重发同一份答案，不会重复作答。
          </p>
        )}
        <div className="exam-submit">
          <span className="field-hint">
            <LockKeyhole size={14} aria-hidden="true" />
            {storageFailed
              ? "当前浏览器无法保存草稿，请勿关闭页面"
              : "草稿自动保留在当前浏览器"}
          </span>
          <button className="button primary" disabled={busy}>
            {busy
              ? "正在保存答案…"
              : locked
                ? "重试提交"
                : last
                  ? "提交并查看结果"
                  : "提交并继续"}
            <ArrowRight size={17} aria-hidden="true" />
          </button>
        </div>
      </form>
      <p className="exam-footnote">
        提交后即进入下一步，模型将在后台独立完成评分。
      </p>
    </section>
  );
}
