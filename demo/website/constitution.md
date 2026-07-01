# Web Constitution

> Version-controlled rule set for front-end work. Every change produced by the
> agent loop is checked against these clauses by the Security Critic before
> convergence. This file is READ-ONLY to the coding agent (the Actor).

## §1 — Semantic HTML
Use elements for their meaning (`<nav>`, `<main>`, `<header>`, `<footer>`,
headings in order). Do not fake structure with bare `<div>`s where a semantic
element exists.

## §2 — Accessible images and links
Every `<img>` MUST have a meaningful, non-empty `alt` attribute. Every link MUST
have a valid `href` (no `href="#"` placeholders or dead links).

## §3 — No inline event handlers or inline styles
No `onclick`/`onload`/`on*` attributes and no `style="..."` attributes in the
markup. Behaviour and presentation live in separate files.

## §4 — No third-party tracking or external calls
No analytics snippets, no external `<script src>` to third-party domains, no
tracking pixels. The page must render fully offline from disk.

## §5 — Valid, self-contained document
A single well-formed `<!DOCTYPE html>` document with `<html>`, `<head>`, and
`<body>`. All referenced local assets (e.g. `styles.css`) exist in the repo.
