import { LegalPage } from "@/components/legal";

export const metadata = { title: "Terms of service" };

export default function Terms() {
  return (
    <LegalPage
      eyebrow="Terms of service"
      title="Read this before you size anything."
      updated="19 September 2026"
    >
      <h2>1. What Curator is</h2>
      <p>
        Curator is a research tool for liquidity providers. It reads public data
        about pools, vaults and wallets, scores it with rules you can inspect in
        the source code, and shows you the result. It never holds funds, never
        signs or sends transactions, and never asks for a private key or seed
        phrase. Signing in with a wallet is a signature over a plain-text
        message (EIP-4361) that costs nothing and moves nothing.
      </p>
      <h2>2. Not financial advice</h2>
      <p>
        Scores, grades, flags, simulations and rotation verdicts are outputs of
        a model with stated assumptions (24h/7d fee history, a σ²/8
        impermanent-loss estimate, a fixed switch cost). They are research
        prompts, not recommendations, and they can be wrong. Liquidity provision
        can lose money, including all of it. You alone decide what to do with
        your capital, and you are responsible for the outcome.
      </p>
      <h2>3. Data comes from third parties</h2>
      <p>
        Pool, vault and position data comes from public APIs operated by others
        (Krystal, DexScreener). Curator does not control their accuracy,
        availability or terms. When a metric is not provided, Curator shows it
        as unknown rather than zero; when a feed is stale, the status bar says
        so. Do not treat any number here as a guaranteed on-chain fact.
      </p>
      <h2>4. Track record</h2>
      <p>
        The public track record is an aggregate of every verdict shown to any
        user, compared with what followed, using the same third-party data. It
        is anonymous and it is published whether it is flattering or not. It is
        a measure of the model, not a promise about future results.
      </p>
      <h2>5. Alerts</h2>
      <p>
        Telegram alerts are best-effort. They depend on third-party feeds,
        Telegram, and this service being up. Missing or late alerts are not a
        breach of these terms. Do not rely on them as your only monitor for
        positions you cannot afford to leave unattended.
      </p>
      <h2>6. Your account</h2>
      <p>
        Keep your wallet and password safe; sessions are yours to end from the
        account menu. You may not use Curator to attack, overload or scrape the
        service or its data sources, or to break the law where you are. We may
        suspend accounts that do.
      </p>
      <h2>7. Referral links</h2>
      <p>
        Links to Krystal carry a referral code. If you use Krystal through them,
        Curator's operator may receive a share of Krystal's fees at no extra
        cost to you. Verdicts and scores do not take this into account; the
        model has no idea which link you click.
      </p>
      <h2>8. Software licence and warranty</h2>
      <p>
        Curator is free software under the GNU Affero General Public License v3.
        It is provided &quot;as is&quot;, without warranty of any kind, and to
        the fullest extent the law allows the operator is not liable for any
        loss arising from its use. The source for this deployment is available
        from the <a href="/source">source page</a>.
      </p>
      <h2>9. Changes</h2>
      <p>
        These terms may change. The date above is the current version; continued
        use after a change means you accept it.
      </p>
    </LegalPage>
  );
}
