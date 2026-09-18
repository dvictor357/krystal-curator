"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ArrowUpRight, Check, Copy, Search } from "lucide-react";
import type { Action } from "@/lib/links";

export interface PaletteRequest {
  title: string;
  subtitle?: string;
  actions: Action[];
}
const PaletteContext = createContext<(req: PaletteRequest) => void>(() => {});
export const usePalette = () => useContext(PaletteContext);

/** Raycast-style action list: filter as you type, arrows + Enter, Esc/backdrop to close. */
export function PaletteProvider({ children }: { children: React.ReactNode }) {
  const [req, setReq] = useState<PaletteRequest | null>(null);
  const open = useCallback((r: PaletteRequest) => setReq(r), []);
  return (
    <PaletteContext.Provider value={open}>
      {children}
      {req && <Palette req={req} close={() => setReq(null)} />}
    </PaletteContext.Provider>
  );
}

function Palette({ req, close }: { req: PaletteRequest; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [copied, setCopied] = useState<string | null>(null);
  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? req.actions.filter((a) =>
          `${a.label} ${a.hint ?? ""}`.toLowerCase().includes(q),
        )
      : req.actions;
  }, [req, query]);
  useEffect(() => {
    dialog.current?.showModal();
    input.current?.focus();
    const el = dialog.current;
    return () => el?.close();
  }, []);
  useEffect(() => setCursor(0), [query]);
  async function run(a: Action) {
    if (a.kind === "copy" && a.copy) {
      try {
        await navigator.clipboard.writeText(a.copy);
        setCopied(a.id);
        window.setTimeout(close, 650);
      } catch {
        setCopied(null);
      }
      return;
    }
    if (a.href) window.open(a.href, "_blank", "noopener,noreferrer");
    close();
  }
  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(items.length - 1, c + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (e.key === "Enter" && items[cursor]) {
      e.preventDefault();
      run(items[cursor]);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="palette"
      aria-label={req.title}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
      onKeyDown={onKey}
    >
      <div className="palette-inner">
        <header className="palette-head">
          <span className="eyebrow">{req.title}</span>
          {req.subtitle && (
            <code className="palette-subject">{req.subtitle}</code>
          )}
        </header>
        <label className="palette-search">
          <Search size={14} />
          <input
            ref={input}
            placeholder="Type to filter…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter actions"
          />
          <kbd>esc</kbd>
        </label>
        <ul className="palette-list" role="listbox">
          {items.map((a, i) => (
            <li key={a.id}>
              <button
                role="option"
                aria-selected={i === cursor}
                className={`palette-item${i === cursor ? " active" : ""}`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => run(a)}
              >
                <span className="palette-icon">
                  {copied === a.id ? (
                    <Check size={14} />
                  ) : a.kind === "copy" ? (
                    <Copy size={14} />
                  ) : (
                    <ArrowUpRight size={14} />
                  )}
                </span>
                <span className="palette-label">
                  {copied === a.id ? "Copied" : a.label}
                  {a.hint && <small>{a.hint}</small>}
                </span>
                {i === cursor && <kbd>↵</kbd>}
              </button>
            </li>
          ))}
          {items.length === 0 && (
            <li className="palette-empty">No matching action.</li>
          )}
        </ul>
      </div>
    </dialog>
  );
}
