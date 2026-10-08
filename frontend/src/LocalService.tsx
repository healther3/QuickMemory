import { useState } from "react";
import { Power, Save, Server } from "lucide-react";
import { message, send, useLoad } from "./api";
import type { components } from "./generated/api-schema";
import { ErrorBox, Loading, Status } from "./ui";

type LocalServiceState = components["schemas"]["LocalServiceView"];

export default function LocalService() {
  const service = useLoad<LocalServiceState>("/local-service");
  const [port, setPort] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "stop" | null>(null);
  const [error, setError] = useState("");
  const [portError, setPortError] = useState("");
  const [status, setStatus] = useState("");
  const [stopping, setStopping] = useState(false);

  const portValue = port ?? String(service.data?.preferred_port ?? "");
  const desktopWindow = service.data?.desktop_window ?? false;

  async function savePort() {
    const preferredPort = Number(portValue);
    if (
      !Number.isInteger(preferredPort) ||
      preferredPort < 1024 ||
      preferredPort > 65535
    ) {
      setPortError("请输入 1024–65535 之间的整数端口。");
      return;
    }
    setBusy("save");
    setError("");
    setStatus("");
    try {
      const saved = await send<LocalServiceState>(
        "/local-service",
        { preferred_port: preferredPort },
        "PUT",
      );
      service.setData(saved);
      setPort(String(saved.preferred_port));
      setStatus(
        `首选端口 ${saved.preferred_port} 已保存。退出后重新启动轻记时生效。`,
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  async function stopService() {
    if (
      !window.confirm(
        desktopWindow
          ? "确认退出轻记？请先保存输入并等待评分完成。应用窗口与后台服务将一起关闭。"
          : "确认关闭本地服务？关闭后网页将无法继续使用，请先保存其他页面的输入并等待评分完成。之后可再次双击“轻记.exe”启动。",
      )
    )
      return;
    setBusy("stop");
    setError("");
    setStatus("");
    try {
      const result = await send<components["schemas"]["LocalServiceStopView"]>(
        "/local-service/stop",
      );
      if (!result.stopping) throw new Error("服务尚未接受关闭请求，请重试。");
      setStopping(true);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      id="local-service"
      className="panel local-service"
      aria-labelledby="local-service-heading"
    >
      <div className="section-heading">
        <div className="section-title-icon">
          <Server size={22} aria-hidden="true" />
          <h2 id="local-service-heading">
            {desktopWindow ? "应用运行" : "本地服务"}
          </h2>
        </div>
        <span className="pill">仅本机访问</span>
      </div>
      {stopping ? (
        <Status>
          <div>
            <strong>已请求关闭本地服务</strong>
            <p>
              服务退出后，此网页将无法继续操作。需要使用时，再次双击“轻记.exe”启动。
            </p>
          </div>
        </Status>
      ) : (
        <>
          <p className="muted">
            {desktopWindow
              ? "关闭应用窗口会同时退出后台服务。最小化可继续运行，题库和设置会保留在本机。"
              : "关闭浏览器后，服务仍会在后台运行。你可以在这里关闭服务，或设置下次启动使用的网页端口。"}
          </p>
          <ErrorBox
            error={error || service.error}
            onRetry={!error && service.error ? service.reload : undefined}
          />
          {service.loading && !service.data && (
            <Loading text="正在读取本地服务状态…" />
          )}
          {status && <Status>{status}</Status>}
          {service.data && (
            <div className="local-service-grid">
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  savePort();
                }}
              >
                <label className="field" htmlFor="local-service-port">
                  下次启动端口
                </label>
                <div className="local-service-port-row">
                  <input
                    id="local-service-port"
                    type="number"
                    required
                    min="1024"
                    max="65535"
                    step="1"
                    value={portValue}
                    disabled={!!busy}
                    aria-invalid={!!portError}
                    aria-describedby={
                      portError
                        ? "local-service-port-error local-service-port-hint"
                        : "local-service-port-hint"
                    }
                    onChange={(event) => {
                      setPort(event.target.value);
                      setPortError("");
                      setStatus("");
                    }}
                  />
                  <button
                    className="button"
                    disabled={
                      !!busy ||
                      portValue === String(service.data.preferred_port)
                    }
                  >
                    <Save size={17} aria-hidden="true" />
                    {busy === "save" ? "正在保存…" : "保存端口"}
                  </button>
                </div>
                {portError && (
                  <p
                    id="local-service-port-error"
                    className="danger-text"
                    role="alert"
                  >
                    {portError}
                  </p>
                )}
                <p id="local-service-port-hint" className="field-hint">
                  端口范围 1024–65535。保存后不会立即重启服务。
                  若首选端口被占用，启动时会自动选择附近可用端口。
                </p>
                {service.data.preferred_port !== service.data.port && (
                  <p className="field-hint">
                    下次启动将优先使用端口 {service.data.preferred_port}。
                  </p>
                )}
              </form>
              <div className="local-service-current">
                <span className="field">
                  {desktopWindow ? "本地服务地址" : "当前网页地址"}
                </span>
                <a
                  href={`http://localhost:${service.data.page_port}`}
                  className="local-service-address"
                >
                  http://localhost:{service.data.page_port}
                </a>
                <div>
                  <button
                    type="button"
                    className="button danger-text"
                    disabled={!!busy || !service.data.can_stop}
                    onClick={stopService}
                  >
                    <Power size={17} aria-hidden="true" />
                    {busy === "stop"
                      ? "正在请求关闭…"
                      : desktopWindow
                        ? "退出轻记"
                        : "关闭本地服务"}
                  </button>
                </div>
                {!service.data.can_stop && (
                  <p className="field-hint">
                    当前启动方式不支持从网页关闭，请在启动服务的终端中停止。
                  </p>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
