# Vendored third-party ESM bundles

These files are checked in so the frontend has **no runtime npm dependency**. They
are served verbatim from `/vendor/` (gulp `copyStatic` copies `web/static/**` →
`web/dist/**` unmodified) and wired into the native browser import map generated in
`src/soundbot/web/routes/index.py`.

## wavesurfer.js — v7.8.6

- `wavesurfer.esm.js`
  - Source: https://unpkg.com/wavesurfer.js@7.8.6/dist/wavesurfer.esm.js
  - Import map specifier: `wavesurfer`
- `regions.esm.js` (Regions plugin)
  - Source: https://unpkg.com/wavesurfer.js@7.8.6/dist/plugins/regions.esm.js
  - Import map specifier: `wavesurfer-regions`

Both are **self-contained bundles**: they contain zero `import` statements and each
only `export{... as default}`. The Regions plugin bundles its own copy of the base
`EventEmitter`/`BasePlugin` classes rather than importing the core, so the two files
resolve independently and there is no cross-file import specifier to patch.

License: BSD-3-Clause (wavesurfer.js). See https://github.com/katspaugh/wavesurfer.js
