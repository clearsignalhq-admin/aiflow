# Changelog

AiFlow follows `MAJOR.MINOR.PATCH`. While the product is in private beta the major number stays at 0: a new feature raises MINOR, a fix raises PATCH. The newest entry is first and must match the `VERSION` file (a test checks this).

## 0.13.0 — 2026-11-24

**New**
- **App introduction video** (AiFlow: Idea to Code, on YouTube). On the landing page, right after the first screen, as a click-to-play section: the page makes no request to YouTube until someone presses play, and the player then loads from the privacy-friendly address (`youtube-nocookie.com`). Also under **Help → App introduction video**, and as a link at the top of the user guide (and its PDF). The video's address lives in one place (`frontend/src/links.ts`) and a test checks the written guide agrees.

## 0.12.2 — 2026-11-24

**Fixed**
- The user guide ignored the light/dark preference and always showed dark. It now follows the stored choice, shared with the editor and the landing page, and has the same toggle button.

**Added**
- A PDF of the user guide: `node make-pdf.mjs` in `docs/user-guide/capture` prints the in-app guide page to `docs/user-guide/AiFlow User Guide.pdf` (A4, light, with a header showing the version and page numbers). The guide page also has print styles, so printing it from a browser (Ctrl/Cmd+P) gives the same result.

## 0.12.1 — 2026-11-24

**Fixed**
- The landing page's GitHub links (navigation, hero, call to action and footer) pointed at an address that returns 404. They now point at the real repository, and a test checks them against this repository's own remote.

**Improved**
- The landing page now describes the product as it is: designing, checking, testing and sharing workflows, in five stages (describe, design, check and fix, test and compare, share and export), instead of stopping at simulation and evaluation.
- A "See it in action" strip with four real screenshots from the user guide.
- The example section shows the twelve real examples (level, step count, industry and a one-line description, all read from the example files) instead of three invented ones, and says one is flawed on purpose.
- "Read the user guide" in the navigation, the hero and the call to action; the technology list no longer claims GPT-4o (the default model is `gpt-4o-mini`).

**Added**
- `scripts/deploy.py` now offers to tag the release after a successful deploy: an annotated `v<VERSION>` tag on the deployed commit, pushed to GitHub. It never moves an existing tag, never tags a dirty tree, and only asks when run from a terminal (`--tag`, `--no-tag`, `--dry-run`). Documented in `docs/deploy.md`.

## 0.12.0 — 2026-11-24

**New**
- Two new examples: **Refund Request Handler** (the safe pattern: a person approves before any money moves) and **Meeting Notes to Action Items** (model, transform and tool in one short flow). There are now twelve.
- `examples/README.md` describes every example and the conventions they follow.

**Improved**
- The examples now follow the standard the product teaches: every outside step is checked and a failure ends the run cleanly or goes to a person, steps declare the fields later steps read, and every message a model writes is reviewed by a person before it goes out. **Supply Chain Monitor** is kept as it was on purpose, labelled as the one to try the checks on.
- The example picker reads each example's difficulty, industry, tags and step count from the example file, so they can no longer drift, and its tiers describe the kind of workflow instead of a step count. A test fails if an example file is not listed.
- A test suite for the examples (160 checks) keeps them valid, clean, safe and exportable.

**Fixed**
- A suggested "failure branch" fix added a human review after a write, and the design check then flagged that review as "approval after an irreversible step". A review reached only through a failure branch (false, no, error, failed) is now understood to be handling the failure. Applying every suggested fix to any example now leaves no findings.
- Removed a stale duplicate of the customer-support example that the picker never showed.
- A fresh editor could look "unsaved" and ask "Discard unsaved changes?" before you had done anything: the canvas reports every step's position when it first lays out, and that was treated as an edit (and recorded as an undo step). Updates that change nothing are now ignored, and "unsaved" now means "differs from the last loaded or saved version", so undoing back to the saved state clears it.

## 0.11.1 — 2026-11-24

**Fixed**
- The user guide could not be scrolled. The editor locks the page so it can fill the window, and the guide page did not scroll inside its own container.
- The same problem on the sign-in, request-access, password and pending pages: in a short window (a small laptop, or a phone with the keyboard open) the form could be cut off with no way to reach the rest. These pages now scroll, and stay centred when they fit.

**Added**
- A test that guards this whole class of bug (full-page screens must scroll in their own container), since component tests cannot see layout.
- The deployment guide (`docs/deploy.md`) now leads with the release routine (`bump_version.py`, `deploy.py`) and keeps the manual steps as the explanation and fallback.

## 0.11.0 — 2026-11-24

**New**
- **Save state** next to the workflow name: "Unsaved changes" while you have edits that are not saved, "Saved to cloud" when the cloud copy matches.
- **Pass rate over time**: a small chart in the Tests dialog of your last twelve finished runs, with how the latest compares to the one before.
- **Save a copy** on a shared page: a signed-in visitor can add the shared workflow to their own cloud workflows.
- **Recent actions**: the action search (Ctrl/⌘+K) shows what you used last first, marked *Recent*, until you start typing.
- **Read more in the user guide** links at the bottom of the ⓘ help dialogs, opening the matching guide section; a **User guide** link and the version number on the landing page.
- Maintenance: the access-request test no longer depends on a developer's local Turnstile secret (it was the one test that failed on a machine with real settings), and a new test checks that the security check is enforced when a key is set. The backend suite now passes fully.
- Maintenance scripts: `scripts/bump_version.py` (start a release) and `scripts/deploy.py` (build and deploy with the commit stamped in, refusing to deploy uncommitted work).

## 0.10.1 — 2026-11-24

**Fixed**
- The suggested "failure branch" fix declared its success flag without a type, so simulations filled it with made-up text that matched neither branch and followed both. It is now a true/false value that is true unless a failure is injected. A workflow fixed this way now simulates down its success path, and the failure drill reports the result correctly (in the Supply Chain Monitor example: nothing left unnoticed, server errors handled by the human reviews, other failures stopping the run visibly).

**Added**
- Video guide storyboards (`docs/video-guide`): four scripts with narration, on-screen notes and screenshots, ready to be turned into videos. Checked by tests so they cannot point at missing screenshots.

## 0.10.0 — 2026-11-24

**New**
- A written user guide with screenshots: **Help → User guide**, also readable without signing in at `/guide`. Linked from the About dialog. The screenshots are regenerated by a script, so they can be kept current.

**Improved**
- Suggested changes keep the list short: each suggestion shows its title and reason, with the full list of edits behind *What this changes*.
- After applying suggestions that add steps, the layout is tidied automatically and the view refits (one Ctrl+Z undoes both); the previous run's highlighting, which no longer matched, is cleared.
- The canvas waits for newly added steps to be measured before fitting the view, so nothing is cropped.
- Text in the version-history and safety dialogs matches the size of the rest of the dialog.

**Fixed**
- The Validate button showed a stray "0" after a check that found no warnings.

## 0.9.0 — 2026-11-24

First tracked release. Everything built so far, by area.

**Design**
- Describe a workflow in plain English and have the AI generate it; refine it with a chat; edit nodes, edges, settings and data contracts on a canvas with undo and redo.
- Grouped top bar (File, Export, Analyze) and a command palette (Ctrl/⌘+K) that finds any action.
- Example library, Mermaid import and export, plain-language explanation of any workflow.

**Check and improve**
- Structural validation and design findings (unreachable steps, dead ends, missing failure branches, review after an irreversible step, data-contract mismatches, cycles).
- Suggested changes: one-click fixes for findings and AI-proposed edits from a plain-language instruction, applied as one undoable edit.
- Safety checks: prompt-injection exposure report and a failure drill that makes each outside step fail in turn.

**Simulate and test**
- Mock and real-model simulation with human-review pauses, saved run history and an AI evaluation.
- Test suites with deterministic checks, coverage, optional real-model runs, and comparison of two runs (what regressed, what was fixed, and what changed in the workflow).

**Share and export**
- Cloud workflows with version history, changes-since and restore; read-only share links.
- Export as a runnable Python, LangGraph or MCP project with real integrations; import a LangGraph project.

**Platform**
- Private access with magic-link sign-in, admin approval, daily allowances, request time budgets, durable pause and resume.
- Version number and About dialog (this release).
