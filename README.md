# tree-sitters

Prebuilt tree-sitter grammar sources for [rtok](https://github.com/pyrlyn/rtok).

Every 3 days (and on manual dispatch) the `build` workflow runs rtok's `scripts/grammars.py fetch`
(pinned commits from `libs/treesitter-native/grammars.json` on rtok `main`) and keeps only what
rtok's `libs/treesitter-native` build compiles. The result is uploaded as a workflow artifact
named `ts-grammars-<YYYY-MM-DD>`. It holds `ts-grammars-<YYYY-MM-DD>.tar.gz` (deterministic tar:
sorted, mtime 0, uid/gid 0, gzip without name/time) and `ts-grammars-<YYYY-MM-DD>.tar.gz.sha256`.

## Artifact contents

The tarball unpacks to exactly rtok's `libs/treesitter-native/build/vendor`, with no top-level folder:

- `tree-sitter/lib/src` and `lib/include`: only the runtime files `lib.c` includes;
- per grammar: `src/parser.c`, `src/scanner.c` (if any), the headers they include, and the upstream `LICENSE`
  (MIT and similar licenses require the notice to ship with the source);
- `rtok_ts_table.c`: the generated grammar table with the `tags`, `locals` and `highlights` queries embedded;
- `grammars.txt`: grammar names and source directories relative to `libs/treesitter-native`.

## Use in rtok

```sh
read -r run name < <(gh api 'repos/pyrlyn/tree-sitters/actions/artifacts?per_page=1' \
  -q '.artifacts[0] | "\(.workflow_run.id) \(.name)"')
gh run download "$run" -R pyrlyn/tree-sitters -n "$name" -D /tmp/ts
(cd /tmp/ts && shasum -a 256 -c "$name.tar.gz.sha256")
mkdir -p libs/treesitter-native/build/vendor
tar xzf "/tmp/ts/$name.tar.gz" -C libs/treesitter-native/build/vendor
./gradlew :treesitter-native:build -x :treesitter-native:fetchGrammars
```

The newest artifact is first in the API list. Without `gh`, call
`https://api.github.com/repos/pyrlyn/tree-sitters/actions/artifacts?per_page=1` and download its
`archive_download_url` with a token (any GitHub token works for a public repo); the zip holds the tarball and
its `.sha256`.

**Artifacts expire after 90 days.** A new one is uploaded only when the content changes, so after a long
quiet period run the workflow manually (`gh workflow run build -R pyrlyn/tree-sitters -f force=true`).

## History

- `history.json`: one entry per uploaded artifact: date, name, tarball sha256 (used to skip duplicates), rtok commit, grammars.json
  sha256, and the fetched / new / unchanged grammar lists.
- `history.log`: the human-readable log of every run, uploaded or skipped.
