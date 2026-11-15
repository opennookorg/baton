import { launchVideoId } from '@/lib/shared';

/** The Baton launch video, embedded from YouTube without tracking cookies. */
export function LaunchVideo({ className = '' }: { className?: string }) {
  return (
    <iframe
      src={`https://www.youtube-nocookie.com/embed/${launchVideoId}?rel=0`}
      title="Baton launch video"
      loading="lazy"
      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
      referrerPolicy="strict-origin-when-cross-origin"
      allowFullScreen
      className={`aspect-video w-full rounded-xl border ${className}`}
    />
  );
}
