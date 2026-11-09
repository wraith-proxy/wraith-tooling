# wraith-tooling

CI, release and lint tooling for the wraith Claude Code plugin. It lives
outside the plugin because the Claude plugin directory accepts only
Markdown, text, JSON, YAML and images from unverified orgs.

## Usage

GitHub Action, pinned to a commit:

```yaml
jobs:
  checks:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@<sha>
      - uses: wraith-proxy/wraith-tooling@<sha>
      - run: wraith-lint-skills
      - run: wraith-file-types
```

pre-commit hooks:

```yaml
repos:
  - repo: https://github.com/wraith-proxy/wraith-tooling
    rev: <sha>
    hooks:
      - id: wraith-lint-skills
      - id: wraith-build-copilot
      - id: wraith-privacy-scan
      - id: wraith-file-types
      - id: wraith-check-plugin
```

One-off with uvx:

```sh
uvx --from git+https://github.com/wraith-proxy/wraith-tooling@<sha> wraith-lint-skills
```

## Commands

Run from the plugin repo root.

| Command | Purpose |
|---|---|
| `wraith-lint-skills` | Lint skills and agents against the repo rules. |
| `wraith-build-copilot` | Generate Copilot agents from `agents/*.md`. |
| `wraith-privacy-scan` | Scan tracked files for private data. |
| `wraith-file-types` | Enforce the plugin directory file policy. |
| `wraith-check-plugin` | Run the plugin content checks. |
| `wraith-sync-upstream` | Merge upstream changes into vendored files. |
| `wraith-sync-commit-type` | Pick the commit type for an upstream sync. |
| `wraith-fetch-upstream` | Fetch upstream sources into the cwd. |
| `wraith-vet-companion` | Draft a companion re-vet for owner merge. |
| `wraith-drift-issues` | Open or close re-vet issues from the drift report. |
| `wraith-release-gate` | Pick the release increment from commit subjects. |
| `wraith-release-notes` | Build final release notes. |

## Development

```sh
uv sync
uv run pytest
```

## Plugin root

The hooks find the plugin folder from `.claude-plugin/marketplace.json`: a single plugin whose `source` is `./<folder>` is linted, built and checked there, and CI, docs and evals stay outside it. A missing marketplace file or `"./"` means the repository root.
