import Link from 'next/link';
import { dashboardUrl } from '@/lib/shared';

const STATS = [
  { value: '70%', label: 'right team on the first guess' },
  { value: '86%', label: 'right team in the top 3' },
  { value: '107', label: 'fewer misroutes per 1,000 issues' },
];

export default function HomePage() {
  return (
    <main className="flex flex-1 flex-col items-center px-4 py-16 text-center md:py-24">
      <img src="/images/logo.svg" alt="" width={64} height={64} className="mb-6" />
      <h1 className="mb-4 max-w-2xl text-3xl font-bold md:text-5xl">
        Send every issue to the team that owns it
      </h1>
      <p className="mb-8 max-w-xl text-fd-muted-foreground md:text-lg">
        Ownership lists go stale the day they are written. Baton learns who owns what from the
        issues that actually get fixed, and shows you why it picked each team.
      </p>
      <div className="mb-14 flex flex-wrap justify-center gap-3">
        <Link
          href="/docs"
          className="rounded-full bg-fd-primary px-5 py-2.5 font-medium text-fd-primary-foreground"
        >
          Read the docs
        </Link>
        <a href={dashboardUrl} className="rounded-full border px-5 py-2.5 font-medium">
          Open the live dashboard
        </a>
      </div>
      <div className="mb-14 grid w-full max-w-3xl gap-4 sm:grid-cols-3">
        {STATS.map((stat) => (
          <div key={stat.label} className="rounded-xl border bg-fd-card p-5">
            <div className="text-3xl font-bold">{stat.value}</div>
            <div className="text-sm text-fd-muted-foreground">{stat.label}</div>
          </div>
        ))}
      </div>
      <img
        src="/images/page-try.png"
        alt="The Baton dashboard routing an issue to sig/api-machinery"
        className="w-full max-w-5xl rounded-xl border shadow-lg"
      />
    </main>
  );
}
