"use client";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { PAGE_SIZES, type usePagination } from "@/lib/paging";

type Paging = ReturnType<typeof usePagination<unknown>>;

/** Standard table footer: caller's note on the left, range + page size + page buttons on the right. */
export function Pager({
  paging,
  note,
  unit = "rows",
}: {
  paging: Paging;
  note?: React.ReactNode;
  unit?: string;
}) {
  const { page, pages, size, setSize, setPage, from, to, total } = paging;
  const window: number[] = [];
  for (let n = Math.max(1, page - 2); n <= Math.min(pages, page + 2); n++)
    window.push(n);
  return (
    <div className="table-footer pager">
      <span className="pager-note">{note}</span>
      <span className="pager-range">
        {total ? `${from}–${to} of ${total}` : `0`} {unit}
      </span>
      <label className="pager-size">
        <span>Rows</span>
        <select
          aria-label="Rows per page"
          value={size}
          onChange={(e) => setSize(Number(e.target.value))}
        >
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      {pages > 1 && (
        <nav className="pager-nav" aria-label="Pagination">
          <button
            className="pager-btn"
            onClick={() => setPage(page - 1)}
            disabled={page === 1}
            aria-label="Previous page"
          >
            <ChevronLeft size={13} />
          </button>
          {window[0] > 1 && (
            <>
              <button className="pager-btn" onClick={() => setPage(1)}>
                1
              </button>
              {window[0] > 2 && <span className="pager-gap">…</span>}
            </>
          )}
          {window.map((n) => (
            <button
              key={n}
              className={`pager-btn${n === page ? " current" : ""}`}
              onClick={() => setPage(n)}
              aria-current={n === page ? "page" : undefined}
            >
              {n}
            </button>
          ))}
          {window[window.length - 1] < pages && (
            <>
              {window[window.length - 1] < pages - 1 && (
                <span className="pager-gap">…</span>
              )}
              <button className="pager-btn" onClick={() => setPage(pages)}>
                {pages}
              </button>
            </>
          )}
          <button
            className="pager-btn"
            onClick={() => setPage(page + 1)}
            disabled={page === pages}
            aria-label="Next page"
          >
            <ChevronRight size={13} />
          </button>
        </nav>
      )}
    </div>
  );
}
