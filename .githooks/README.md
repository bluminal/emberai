# Git Hooks

This directory contains shared git hooks for the Netex Suite repository.

## Setup

Configure git to use these hooks instead of the default `.git/hooks/` directory:

```bash
git config core.hooksPath .githooks
```

This is a per-repository setting and must be run once after cloning.

## Hooks

### pre-commit

Runs [gitleaks](https://github.com/gitleaks/gitleaks) on staged changes to prevent secrets (API keys, tokens, passwords) from being committed.

**Requires:** `gitleaks` installed locally. If gitleaks is not found, the hook prints a warning and allows the commit to proceed.

**Install gitleaks:**

- macOS: `brew install gitleaks`
- Linux: Download from [GitHub releases](https://github.com/gitleaks/gitleaks/releases)
- Go: `go install github.com/gitleaks/gitleaks/v8@latest`

### Bypassing the hook

In rare cases where the hook produces a false positive that cannot be resolved with an allowlist entry, you can bypass it:

```bash
git commit --no-verify
```

**This should be rare.** If you find yourself bypassing frequently, update `.gitleaks.toml` with an appropriate allowlist entry instead.
