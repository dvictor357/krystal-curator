import Link from "next/link";
export function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Curator home">
      <span className="brand-mark" aria-hidden="true">
        c<span>›</span>
      </span>
      curator<span className="brand-dot">.</span>
    </Link>
  );
}
