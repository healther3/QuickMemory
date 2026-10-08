import { useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { api, message, send, useLoad, type Named } from "./api";
import { ErrorBox, Loading } from "./ui";
export default function NamedManager({
  path,
  onChange,
}: {
  path: string;
  onChange?: () => void;
}) {
  const { data, error, loading, reload } = useLoad<Named[]>(path);
  const [name, setName] = useState(""),
    [editing, setEditing] = useState<number | null>(null),
    [rename, setRename] = useState(""),
    [failure, setFailure] = useState(""),
    [busy, setBusy] = useState(false);
  async function save(id?: number) {
    if (!(id ? rename : name).trim()) return;
    setBusy(true);
    setFailure("");
    try {
      await send(
        `${path}${id ? `/${id}` : ""}`,
        { name: (id ? rename : name).trim() },
        id ? "PUT" : "POST",
      );
      setName("");
      setEditing(null);
      reload();
      onChange?.();
    } catch (e) {
      setFailure(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function remove(item: Named) {
    if (
      !window.confirm(
        `确认删除「${item.name}」？此操作会同步移除现有记录上的该标签。`,
      )
    )
      return;
    setBusy(true);
    try {
      await api(`${path}/${item.id}`, { method: "DELETE" });
      reload();
      onChange?.();
    } catch (e) {
      setFailure(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <ErrorBox error={error || failure} />
      {loading && !data ? (
        <Loading />
      ) : (
        <div className="named-list">
          {data?.map((item) => (
            <div className="named-row" key={item.id}>
              {editing === item.id ? (
                <>
                  <input
                    aria-label="新名称"
                    value={rename}
                    onChange={(e) => setRename(e.target.value)}
                    maxLength={100}
                  />
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="保存名称"
                    disabled={busy || !rename.trim()}
                    onClick={() => save(item.id)}
                  >
                    <Check size={18} />
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="取消重命名"
                    onClick={() => setEditing(null)}
                  >
                    <X size={18} />
                  </button>
                </>
              ) : (
                <>
                  <span>{item.name}</span>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`重命名${item.name}`}
                    onClick={() => {
                      setEditing(item.id);
                      setRename(item.name);
                    }}
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    type="button"
                    className="icon-button danger-text"
                    aria-label={`删除${item.name}`}
                    disabled={busy}
                    onClick={() => remove(item)}
                  >
                    <Trash2 size={16} />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <input
          aria-label="新增名称"
          placeholder="输入新名称"
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="button" disabled={busy || !name.trim()}>
          <Plus size={17} aria-hidden="true" />
          添加
        </button>
      </form>
    </>
  );
}
