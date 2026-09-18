import { AmbientField } from "@/components/ambient";
import { OpenCurator } from "@/components/open-curator";
import Image from "next/image";
import Link from "next/link";
import {
  ArrowUpRight,
  ArrowRight,
  ScanLine,
  Crosshair,
  Layers3,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { PairMark } from "@/components/pair";
import snapshot from "@/lib/demo.json";
import { uniquePairs } from "@/lib/pair";
import { money, type Pool } from "@/lib/types";

export default function Home() {
  const book = snapshot.balanced as Pool[];
  const pools = book.slice(0, 5);
  const rail = uniquePairs(book, 7);
  return (
    <div className="landing-page">
      <header className="site-header">
        <Brand />
        <nav aria-label="Main navigation">
          <a href="#book">The book</a>
          <a href="#method">How it works</a>
          <Link href="/demo">
            Demo <ArrowUpRight size={14} />
          </Link>
        </nav>
        <OpenCurator />
      </header>
      <AmbientField density={52} />
      <main id="main">
        <section className="hero wrap">
          <div className="hero-copy">
            <div className="eyebrow">
              <span className="status-dot" /> Robinhood first · USDG quote
            </div>
            <h1>
              See both sides
              <br />
              of the pool.
            </h1>
            <p>
              Curator is a workspace for liquidity providers. Rank concentrated
              pairs by real fees, depth, and risk — then keep a private
              watchlist. You still size the range.
            </p>
            <div className="hero-actions">
              <OpenCurator className="button">Start screening</OpenCurator>
              <Link href="/demo" className="text-link">
                Open the sample book <ArrowRight size={17} />
              </Link>
            </div>
            <div className="hero-note">
              <span>Read-only analytics</span>
              <span>Signature-only sign-in, never a transaction</span>
            </div>
          </div>
          <div className="hero-art">
            <Image
              src="/observatory.png"
              alt="An amber-lit orbital observatory, an instrument for finding patterns in complexity"
              width={1536}
              height={1024}
              priority
              sizes="(max-width: 760px) 100vw, 58vw"
            />
            <span className="art-index">Fig. 01 — Liquidity observatory</span>
          </div>
        </section>
        <div className="source-strip">
          <div className="wrap">
            <span>Live pairs in the sample book</span>
            <div className="pair-rail" aria-label="Sample token pairs">
              {rail.map((p) => (
                <Link href="/demo" key={p.id} className="pair-chip">
                  <PairMark pool={p} size="sm" showMeta={false} />
                </Link>
              ))}
            </div>
            <span className="source-note">
              Krystal feed · scored independently
            </span>
          </div>
        </div>
        <section className="section wrap" id="book">
          <div className="section-heading">
            <div>
              <div className="eyebrow">The book</div>
              <h2>
                One pair.
                <br />
                Then the numbers.
              </h2>
            </div>
            <p>
              Two tokens, a fee tier, and a grade. Open a row before you think
              about size.
            </p>
          </div>
          <div className="terminal-preview">
            <div className="preview-bar">
              <span>
                <span className="status-dot" /> Pool screener
              </span>
              <span>Sample snapshot · not live</span>
            </div>
            <div className="preview-toolbar">
              <span className="chip">Robinhood</span>
              <span className="chip">Balanced</span>
              <span className="chip">Quoted in USDG</span>
              <Link href="/demo">
                Open the full book <ArrowUpRight size={15} />
              </Link>
            </div>
            <div
              className="table-scroll"
              role="region"
              aria-label="Sample pool comparison"
              tabIndex={0}
            >
              <table>
                <thead>
                  <tr>
                    <th>Pair</th>
                    <th>TVL</th>
                    <th>24h fees</th>
                    <th>Grade</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {pools.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <PairMark pool={p} quote="USDG" />
                      </td>
                      <td>{money(p.tvl, true)}</td>
                      <td className="positive">{money(p.fees, true)}</td>
                      <td>
                        <span className={`grade grade-${p.grade}`}>
                          {p.grade}
                        </span>
                      </td>
                      <td className="amber">
                        {p.score.toFixed(1)}{" "}
                        <span className="score-track">
                          <i style={{ width: `${p.score}%` }} />
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="preview-bottom">
              <span>Fees, depth, and risk on one line</span>
              <span>Built for people who still pick their range</span>
            </div>
          </div>
        </section>
        <section className="section wrap" id="method">
          <div className="section-heading">
            <div>
              <div className="eyebrow">How it works</div>
              <h2>
                Yield is a line.
                <br />
                <span className="muted">The pair is the story.</span>
              </h2>
            </div>
            <Link href="/demo" className="text-link">
              Try it on sample data <ArrowUpRight size={18} />
            </Link>
          </div>
          <div className="feature-grid">
            {[
              {
                icon: ScanLine,
                title: "Screen the universe",
                text: "Filter by network, protocol, quote token, and risk profile. Rank real 24h fees next to depth.",
              },
              {
                icon: Crosshair,
                title: "Read the trade-off",
                text: "Open a pair for volatility, missing metrics, and what a deposit of your size would do to the pool.",
              },
              {
                icon: Layers3,
                title: "Keep a shortlist",
                text: "Save pools privately, watch public vault track records, and inspect LP positions on a saved wallet.",
              },
            ].map((f) => (
              <article key={f.title}>
                <div className="feature-top">
                  <f.icon size={27} strokeWidth={1.3} />
                </div>
                <h3>{f.title}</h3>
                <p>{f.text}</p>
              </article>
            ))}
          </div>
        </section>
        <section className="closing wrap">
          <div>
            <div className="eyebrow">Research first. Capital second.</div>
            <h2>
              Open the book.
              <br />
              Keep the call.
            </h2>
          </div>
          <OpenCurator className="button">Create a workspace</OpenCurator>
        </section>
      </main>
      <footer className="site-footer wrap">
        <Brand />
        <span>A research desk for LPs. You still make the trade.</span>
        <a href="/license.txt">
          AGPL-3.0 license <ArrowUpRight size={13} />
        </a>
        <a href="/source">
          Source code <ArrowUpRight size={13} />
        </a>
        <span className="mono">© {new Date().getFullYear()} Curator</span>
      </footer>
    </div>
  );
}
