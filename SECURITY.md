# Security

Lemory is a **local-first** tool: it runs on your machine, against your own
Obsidian vault, and by default sends nothing anywhere except the embedding /
generation API you configured (or nothing at all in the fully-local and
keyless modes). This document describes the trust model and how to report a
problem.

## Trust model

- **The vault is the source of truth.** The SQLite index is derived and
  disposable — delete `<vault>/.lemory/` (or your `data_dir`) and re-index.
- **Writes never leave the vault.** `save_memory`, `append_note`, and the
  chat/PDF importers only ever create or append Markdown files inside the
  vault root. Path traversal (`..`, absolute paths, prefix-sibling
  directories, symlinks that resolve outside the vault) is rejected.
- **Deletion is guarded and recoverable.** `POST /memory/trash` (and the
  console's undo button) moves a note to `<vault>/.trash` (Obsidian's own
  trash) rather than deleting it, and refuses any note that does not carry
  the `lemory_generated: true` marker Lemory stamps on notes it creates — so
  a human-authored note can never be trashed through this path, even one that
  happens to have a `source:` field.
- **Privacy is a file property.** Add `lemory: false` to any note's
  frontmatter and it is never indexed, never retrieved, and never sent to any
  model — retroactively removed from the index if it was there before.

## The local HTTP server

`lemory serve` binds `127.0.0.1` and has **no authentication** — it is meant
for a single local user, like most localhost dev servers. Two guards limit
the blast radius of a hostile web page in the same browser:

- **CORS** is restricted to `app://obsidian.md`, `http://localhost`, and
  `http://127.0.0.1`.
- **Host-header allowlist** rejects any request whose `Host` is not a
  localhost value (`421`). This defeats DNS-rebinding, where a malicious site
  points its own hostname at `127.0.0.1` to become same-origin.

Still, treat the server as trusted-local-only: do not expose the port to
other machines or the internet, and do not run it on a shared host where you
don't trust other local users. If you need remote access, tunnel it (SSH /
Tailscale) rather than binding a public interface.

## Keys

API keys live in `~/.lemory/env` (owner-only, `600`) or your environment —
never in the vault, never in the SQLite index, never committed. `lemory
doctor` and error messages redact them.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Instead, use
GitHub's private vulnerability reporting (Security → Report a vulnerability)
on the repository, or email the maintainer listed in `pyproject.toml`.
Include reproduction steps; we aim to acknowledge within a few days.
