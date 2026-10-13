import "./shell.css";

const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL;

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="page site-footer-row">
        <p>Synthetic network and data. Times are shown in Africa/Tunis (UTC+1).</p>
        {REPO_URL ? (
          <a href={REPO_URL} rel="noreferrer noopener" target="_blank">
            Source code
          </a>
        ) : null}
      </div>
    </footer>
  );
}
