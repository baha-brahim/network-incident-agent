const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL;

export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex w-full max-w-[88rem] flex-wrap items-center justify-between gap-x-6 gap-y-1 px-4 py-4 text-xs text-muted sm:px-6">
        <p>Synthetic network and data. Times are shown in Africa/Tunis (UTC+1).</p>
        {REPO_URL ? (
          <a href={REPO_URL} rel="noreferrer noopener" target="_blank" className="underline-offset-2 hover:text-fg hover:underline">
            Source code
          </a>
        ) : null}
      </div>
    </footer>
  );
}
