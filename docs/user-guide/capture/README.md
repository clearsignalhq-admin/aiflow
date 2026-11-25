# Regenerating the user guide screenshots

The screenshots in `../images` are taken by driving the real interface with Playwright, so they can be redone whenever the interface changes.

```
cd docs/user-guide/capture
node run.mjs            # all 25 screenshots, from a clean state
node run.mjs 14         # only those whose name starts with 14 (the other steps still run, so state builds up)
```

`run.mjs` starts two things, runs `capture.mjs`, then stops them:

- **`server.py`**, a local copy of the real backend on port 8765. Everybody is signed in as a fixed demo user, saved things live in memory, and the AI provider is a canned stand-in. It runs from this folder so the real `backend/.env` (and its secrets) is never read, and it never talks to Supabase or an AI service.
- **The frontend** (`npx vite`) on port 5199, pointed at that backend with fake Supabase values. The script puts a non-expiring fake session in the browser, so there is no sign-in.

Neither server uses the ports of a normal development setup (8000 and 5173), so a running dev environment is left alone.

## The PDF

```
node make-pdf.mjs      # writes docs/user-guide/AiFlow User Guide.pdf
```

It prints the in-app guide page (`/guide`) with a browser, in light mode on A4, so the PDF always matches what the app shows. No backend is needed. Regenerate it after changing the guide or the screenshots. The file is not committed (it goes stale with every guide change); attach a fresh one to a release if you want to hand it out.

## Needs

- `backend/.venv` with the backend requirements installed (`pip install -r backend/requirements.txt`)
- `frontend/node_modules` (`npm ci`) and Playwright's Chromium (`npx playwright install chromium`)

## When you change the interface

1. Run `node run.mjs`, look at the changed pictures, commit them with the change.
2. If a step in `capture.mjs` fails, the interface probably changed under it: the failing line names what it was looking for.
3. Update `../README.md` if the wording no longer matches what the pictures show.

The guide itself is `../README.md`. The app shows the same file at `/guide` (Help → User guide), reading the screenshots from `../images`.
