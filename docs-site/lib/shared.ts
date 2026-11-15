import { createGetUrl } from 'fumadocs-core/source';

export const appName = 'Baton';
export const docsRoute = '/docs';
export const dashboardUrl = 'https://baton-134858271117.us-central1.run.app';
export const docsImageRoute = '/og/docs';

export const gitConfig = {
  user: 'opennookorg',
  repo: 'baton',
  branch: 'main',
};

const getImageUrl = createGetUrl(docsImageRoute);

export function getPageImageUrl(page: { slugs: string[]; locale?: string }) {
  const segments = [...page.slugs, 'image.png'];

  return { segments, url: getImageUrl(segments, page.locale) };
}
