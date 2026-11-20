# Baton docs

The documentation site, built with [Fumadocs](https://fumadocs.dev) as a static export. Pages are MDX in `content/docs/`, images in `public/images/`.

```sh
npm install
npm run dev     # http://localhost:3000
npm run build   # static site in out/
```

Deploy: `scripts/deploy_docs.sh <gcp-project-id>` from the repo root.
