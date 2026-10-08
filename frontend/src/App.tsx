import { Suspense, lazy, useEffect, useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  Link,
} from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  ChartNoAxesCombined,
  ChevronsRight,
  FolderOpen,
  Layers3,
  LockKeyhole,
  Menu,
  Settings2,
  X,
} from "lucide-react";
import { Loading } from "./ui";
const Cards = lazy(() => import("./pages/Cards"));
const Editor = lazy(() => import("./pages/Editor"));
const Folders = lazy(() => import("./pages/Folders"));
const Import = lazy(() => import("./pages/Import"));
const Exam = lazy(() => import("./pages/Exam"));
const Results = lazy(() => import("./pages/Results"));
const Stats = lazy(() => import("./pages/Stats"));
const Settings = lazy(() => import("./pages/Settings"));
const History = lazy(() => import("./pages/History"));
const nav = [
  { to: "/cards", label: "卡片管理", icon: Layers3 },
  { to: "/folders", label: "文件夹", icon: FolderOpen },
  { to: "/stats", label: "统计看板", icon: ChartNoAxesCombined },
  { to: "/settings", label: "设置", icon: Settings2 },
];
export default function App() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => {
    setOpen(false);
    document.title = "QuickMemory · 概念记忆";
    const timer = setTimeout(() => document.getElementById("main")?.focus(), 0);
    return () => clearTimeout(timer);
  }, [location.pathname]);
  useEffect(() => {
    if (!open) return;
    document.querySelector<HTMLElement>(".sidebar nav a")?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        document.querySelector<HTMLElement>(".mobile-menu")?.focus();
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <Link to="/cards" className="brand">
          <span className="brand-mark">
            <BookOpen size={22} strokeWidth={1.6} aria-hidden="true" />
          </span>
          <div>
            <strong>QuickMemory</strong>
            <span>把概念，记得更清楚。</span>
          </div>
        </Link>
        <div className="nav-label">我的学习空间</div>
        <nav id="primary-nav" aria-label="主导航">
          {nav.map(({ to, label, icon: Icon }, index) => (
            <NavLink key={to} to={to} onClick={() => setOpen(false)}>
              <Icon size={20} strokeWidth={1.7} aria-hidden="true" />
              <span>{label}</span>
              <small>0{index + 1}</small>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="line-accent" />
          <p>理解，然后记住。</p>
          <span>
            每一次回想，
            <br />
            都让知识更近一步。
          </span>
        </div>
        <div className="local-badge">
          <LockKeyhole size={16} aria-hidden="true" />
          <div>
            <strong>你的本地工作台</strong>
            <span>数据保存在这台电脑</span>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <div className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label={open ? "关闭导航" : "打开导航"}
            aria-expanded={open}
            aria-controls="primary-nav"
            onClick={() => setOpen(!open)}
          >
            {open ? <X size={22} /> : <Menu size={22} />}
          </button>
          <span>学习空间</span>
          <ChevronsRight size={14} aria-hidden="true" />
          <strong>
            {nav.find((item) => location.pathname.startsWith(item.to))?.label ||
              (location.pathname.includes("results")
                ? "考试结果"
                : location.pathname.includes("exam")
                  ? "概念默写"
                  : "导入题库")}
          </strong>
          <Link to="/folders" className="topbar-link">
            开始一次回想 <ArrowUpRight size={15} aria-hidden="true" />
          </Link>
        </div>
        <main id="main" tabIndex={-1}>
          <Suspense fallback={<Loading />}>
            <Routes key={location.pathname}>
              <Route path="/" element={<Navigate to="/cards" replace />} />
              <Route path="/cards" element={<Cards />} />
              <Route path="/cards/new" element={<Editor />} />
              <Route path="/cards/:id/edit" element={<Editor />} />
              <Route path="/cards/:id/history" element={<History />} />
              <Route path="/folders" element={<Folders />} />
              <Route path="/import" element={<Import />} />
              <Route path="/exams/:id" element={<Exam />} />
              <Route path="/exams/:id/results" element={<Results />} />
              <Route path="/stats" element={<Stats />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/cards" replace />} />
            </Routes>
          </Suspense>
        </main>
        <footer className="page-footer">
          <span>QuickMemory</span>
          <span>专注记忆 · 由你定义</span>
        </footer>
      </div>
    </div>
  );
}
