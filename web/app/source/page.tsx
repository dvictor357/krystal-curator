import { Brand } from "@/components/brand";
export default function Source() {
  const source = process.env.CURATOR_SOURCE_URL;
  return (
    <>
      <header className="site-header">
        <Brand />
      </header>
      <main id="main" className="wrap section">
        <div className="eyebrow">OPEN SOURCE / AGPL-3.0</div>
        <h1>Built in the open.</h1>
        <p>
          Curator is free software under the GNU Affero General Public License,
          version 3.
        </p>
        {source && /^https:\/\//.test(source) ? (
          <a className="button" href={source}>
            Get this deployment’s source ↗
          </a>
        ) : (
          <p className="notice">
            This local preview has not been published. Deployment operators must
            provide the corresponding source link before launching a modified
            network service.
          </p>
        )}
        <p>
          <a href="/license.txt">Read the license</a>
        </p>
      </main>
    </>
  );
}
