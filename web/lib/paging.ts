import { useEffect, useMemo, useState } from "react";

export const PAGE_SIZES = [25, 50, 100] as const;
const KEY = "curator:pagesize";

function storedSize(): number {
  try {
    const n = Number(localStorage.getItem(KEY));
    return (PAGE_SIZES as readonly number[]).includes(n) ? n : 25;
  } catch {
    return 25;
  }
}

/** Client-side paging over an already-loaded list; page size is remembered per browser. */
export function usePagination<T>(items: T[], resetKey: string = "") {
  const [size, setSizeState] = useState(25);
  const [page, setPage] = useState(1);
  useEffect(() => setSizeState(storedSize()), []);
  const pages = Math.max(1, Math.ceil(items.length / size));
  useEffect(() => {
    setPage(1);
  }, [resetKey, items.length, size]);
  const current = Math.min(page, pages);
  const rows = useMemo(
    () => items.slice((current - 1) * size, current * size),
    [items, current, size],
  );
  function setSize(next: number) {
    setSizeState(next);
    try {
      localStorage.setItem(KEY, String(next));
    } catch {
      // per-browser convenience only
    }
  }
  return {
    rows,
    page: current,
    pages,
    size,
    setSize,
    setPage: (n: number) => setPage(Math.min(pages, Math.max(1, n))),
    from: items.length ? (current - 1) * size + 1 : 0,
    to: Math.min(items.length, current * size),
    total: items.length,
  };
}
