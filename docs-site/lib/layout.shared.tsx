import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { appName, dashboardUrl, gitConfig } from './shared';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <>
          <img src="/images/logo.svg" alt="" width={24} height={24} />
          {appName}
        </>
      ),
    },
    links: [{ text: 'Live dashboard', url: dashboardUrl, external: true }],
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
  };
}
