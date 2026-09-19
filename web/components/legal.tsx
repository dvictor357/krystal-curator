import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Brand } from "@/components/brand";

/** Shared frame for the legal pages: header, dated eyebrow, prose column. */
export function LegalPage({
  eyebrow,
  title,
  updated,
  children,
}: {
  eyebrow: string;
  title: string;
  updated: string;
  children: React.ReactNode;
}) {
  return (
    <div className="landing-page">
      <header className="site-header">
        <Brand />
        <Link href="/" className="text-link">
          <ArrowLeft size={16} /> Back to home
        </Link>
      </header>
      <main id="main" className="wrap section legal">
        <div className="eyebrow">
          {eyebrow} · updated {updated}
        </div>
        <h1>{title}</h1>
        {children}
        <p className="fine-print">
          Questions: open an issue on the{" "}
          <Link href="/source">source repository</Link>. See also{" "}
          <Link href="/terms">Terms of service</Link> and{" "}
          <Link href="/privacy">Privacy policy</Link>.
        </p>
      </main>
    </div>
  );
}
