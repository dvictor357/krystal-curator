import { LegalPage } from "@/components/legal";

export const metadata = { title: "Privacy policy" };

export default function Privacy() {
  return (
    <LegalPage
      eyebrow="Privacy policy"
      title="What we keep, and why."
      updated="19 September 2026"
    >
      <h2>What we store</h2>
      <ul>
        <li>
          <strong>Account</strong> — your wallet address (if you sign in with a
          wallet) or your email and an Argon2 hash of your password (never the
          password itself). One session cookie, HttpOnly, seven days, plus a
          non-secret cookie that only says &quot;signed in&quot; so the landing
          page can skip the sign-in flow.
        </li>
        <li>
          <strong>Preferences</strong> — risk profile, network, simulation size,
          the public wallet you asked us to monitor, your Telegram chat ID if
          you set one, and whether alerts are on.
        </li>
        <li>
          <strong>Watchlist</strong> — pool ids you starred.
        </li>
        <li>
          <strong>Verdict log</strong> — every rotation verdict we showed you:
          position id, verdict, the alternative pool, our predictions and your
          position&apos;s fee total at that moment. This is how the track record
          is computed.
        </li>
        <li>
          <strong>Alert state</strong> — what the alert loop last saw per
          position, so it only messages you on changes.
        </li>
        <li>
          <strong>Rate-limit counters</strong> — hashed keys with request counts
          per window.
        </li>
      </ul>
      <h2>What we do not store</h2>
      <p>
        Private keys or seed phrases (never asked for), transaction signatures
        beyond the one-time sign-in message (verified, then discarded), IP
        addresses in the database (only a hashed, short-lived rate-limit key),
        page-view analytics, advertising identifiers, or third-party tracking
        cookies. There are no ads and no trackers.
      </p>
      <h2>Where data goes</h2>
      <ul>
        <li>
          <strong>Krystal and DexScreener</strong> receive the public wallet
          address or pool ids needed to answer a request. They never see your
          account.
        </li>
        <li>
          <strong>Telegram</strong> receives alert messages for the chat ID you
          entered.
        </li>
        <li>
          <strong>The public track record</strong> is an aggregate: counts,
          medians and rates. No wallet, position, pool or account is published.
        </li>
        <li>Nothing is sold or shared with anyone else.</li>
      </ul>
      <h2>Browser storage</h2>
      <p>
        Your browser keeps a per-tab cache of the last data it fetched (cleared
        on sign-out), your page size and a few display preferences. None of it
        leaves your device.
      </p>
      <h2>Retention and deletion</h2>
      <p>
        Data stays while your account exists. Signing out deletes the session.
        To delete the account and everything attached to it, ask via the source
        repository; deletion removes the account, preferences, watchlist,
        verdict log and alert state. Aggregate track-record numbers already
        published are not affected, as they contain nothing identifying.
      </p>
      <h2>Security</h2>
      <p>
        Passwords are hashed with Argon2, sessions are random tokens stored
        hashed, sign-in messages are bound to this site and a single-use nonce,
        and every outbound error has secrets scrubbed before it is logged. If
        you find a problem, report it through the source repository before
        disclosing it.
      </p>
      <h2>Changes</h2>
      <p>The date above is the current version of this policy.</p>
    </LegalPage>
  );
}
