# AiFlow — Questions and Answers Log

## About this document (read first)

**Purpose:** a running, dated log of the owner's strategic/technical questions about AiFlow and Devin's answers. It is a thinking record, not a spec. Nothing here is a commitment until it is promoted into `BACKLOG.md` / `TASKS.md`.

**How to use it**
- Entries are appended **chronologically** (oldest first). Never rewrite an old answer; if later facts change the conclusion, add a dated `Update:` line under that entry.
- Each entry has: a numbered ID (`Q1`, `Q2`, …), the date, the question as asked, then `Devin's Answer:`.
- Answers are grounded in the repo as it was **on the date of the entry**. Code references (files, functions) may have moved since. Re-verify before acting.
- Answers contain opinions and recommendations. They are meant to be challenged and evaluated, not trusted blindly. Claims about the codebase are verified against files; claims about external tools/pricing/platform behaviour come from general knowledge and should be re-checked before committing money or time.
- Related, dated idea dumps live next to this file (e.g. `2026-11-24 AiFlow - Future Directions.md`). Those are broad brainstorms; this file is for specific questions.

**Index**

| ID | Date | Topic |
|---|---|---|
| Q1 | 2026-11-24 | Desktop versions (Windows/macOS/Linux) of the same app via Tauri |

---

## Q1 — 2026-11-24 — Desktop app (Tauri) alongside the online app

### Question

> Besides an online app, in the same repo I want to create desktop versions of the app too for Windows, Mac and Linux, probably using Tauri, totally the same app: one works online, the others work as desktop: same db, same access, same features. State your thoughts, along with advantages and disadvantages, and other things I cannot think of now.

### Devin's Answer:

**Short answer:** feasible, and cheaper for AiFlow than for most apps, because the frontend is already a pure client of a hosted API. Plan it as *"the same React app in a native shell, talking to the same FastAPI + Supabase"*, not as a second product. The real costs are not the Tauri wrapper itself; they are signing/distribution, auth redirects, file handling, WebView differences, and version skew between old installed clients and a newer backend. A few of these interact with decisions already made in MVP2.5 (gated access).

#### 1. What I checked in the repo (why it is cheap)

| Finding | Evidence | Implication |
|---|---|---|
| Backend URL is configuration, not hardcoded | `frontend/src/config.ts`: `API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'` | A desktop build only needs a different env at build time |
| All secrets are server-side; browser only holds Supabase URL + anon key | `frontend/src/lib/supabase.ts`, CLAUDE.md rules | A desktop binary carries nothing that the web bundle doesn't already expose. No new secret-handling problem |
| Authorization is enforced by the backend and Supabase RLS, not the UI | MVP2.5 spec, `core/auth.py`, `user_routes.py` | "Same db, same access" is automatic: desktop is just another client of the same API |
| Business logic is in the backend, UI in React | CLAUDE.md architecture | No logic needs to be rewritten in Rust |
| Workflow save/open uses browser APIs: blob download and `<input type="file">` | `App.tsx`, `ReportModal.tsx` | Works in a webview in some cases but is the weakest part natively (see §4) |
| CORS is an allow-list | `core/config.py`: `cors_origins = ["http://localhost:5173"]`, used in `main.py` | Desktop origins must be added (see §4) |
| Password-reset redirect is built from `window.location.origin` | `ForgotPasswordPage.tsx:48` | Breaks inside a desktop shell (see §4) |
| Cloudflare Turnstile widget on Login / Request Access / Forgot Password | `LoginPage.tsx`, `RequestAccessPage.tsx`, `ForgotPasswordPage.tsx` | Needs a decision for desktop (see §4) |
| Session stored by `supabase-js` (default localStorage) | `lib/supabase.ts` | Works in a webview; consider OS keychain later |

#### 2. Architecture I would use

```
                       ┌──────────────────────────────┐
                       │ frontend/ (React + Vite)     │  ← single codebase
                       └───────┬──────────────┬───────┘
                               │              │
                  vite build   │              │  vite build (desktop mode)
                               ▼              ▼
                    Web (Amplify)        desktop/src-tauri  (Tauri 2 shell)
                                           ├─ Windows  (WebView2)
                                           ├─ macOS    (WKWebView)
                                           └─ Linux    (WebKitGTK)
                               │              │
                               └──────┬───────┘
                                      ▼
                         FastAPI backend (same URL)  →  Supabase (same DB / Auth / RLS)
```

- **Keep one frontend.** Put the Tauri project in `desktop/` (or `frontend/src-tauri/`, which is Tauri's default) pointing at `frontend/dist`. Do not fork the UI.
- **Introduce a `platform` service** in `frontend/src/services/platform.ts` with an interface such as `saveFile`, `openFile`, `openExternal`, `getAppVersion`, `isDesktop`. Web implementation = what exists today; desktop implementation = Tauri plugins. This follows the existing rule "business logic in `services/`, not components". All native differences hide behind it, so "totally the same app" stays true at the component level.
- **Backend stays hosted.** Do not bundle the Python backend into the desktop app (see "sidecar" under §6).
- **Two ways to load the UI in Tauri**, choose deliberately:

| Mode | How | Pros | Cons |
|---|---|---|---|
| **Bundled assets** (recommended) | Vite build is packaged inside the app | Fast start, works with offline shell, strong security model, no dependence on website being up | Installed clients lag behind the web; need an updater and API version discipline |
| **Remote URL** | Webview just loads `https://aiflow...` | Zero version skew, trivially "the same app" | It is just a browser wrapper; no offline; loading remote content in a webview with native IPC access is a security risk; weaker app-store/signing story; little value over a PWA |

#### 3. Advantages

1. **Very small effort for the core.** Because of the points in §1, a working desktop shell is days, not weeks.
2. **Small and fast.** Tauri installers are typically ~5–15 MB and use far less memory than Electron because they use the OS webview.
3. **Same access control for free.** One identity system, one authorization layer, one set of usage limits. Admin approval, demo limits, and rate limits from MVP2.5 apply to desktop users automatically.
4. **Native capabilities the browser lacks** (this is the real reason to build it):
   - Real Save/Open dialogs, file associations (`.aiflow.json` opens in AiFlow), recent files, drag-a-file-onto-the-app.
   - OS keychain for secrets (e.g., user-supplied LLM keys, "bring your own key" mode).
   - Deep links (`aiflow://...`) for auth callbacks and "open this workflow".
   - System notifications for long runs; tray; native menus; auto-update.
   - Access to local resources, notably **a local LLM** (Ollama / LM Studio) for private or free simulations/evaluations.
5. **Credibility for the portfolio/job-search audience** (MVP2.5): a signed cross-platform native app reads as a serious engineering project.
6. **Rust backend option later.** Heavy local work (large-graph analysis, local dataset runs from the evaluator ideas) can be moved into Tauri commands if ever needed.
7. **Mobile is a bonus path.** Tauri 2 also targets iOS/Android from the same frontend, if ever wanted.
8. **Security model is good by default.** Tauri 2 uses explicit capability permissions; the frontend gets only the native APIs you grant.

#### 4. Disadvantages and concrete problems to solve

**Auth and redirects (highest risk to plan for)**
- `ForgotPasswordPage` sends users a link built from `window.location.origin`. In a desktop shell the origin is `tauri://localhost` (macOS/Linux) or `http://tauri.localhost` (Windows), which is not a reachable URL from an email. Options: (a) desktop's "Forgot password" opens the web app in the system browser (simplest); (b) register a deep-link scheme `aiflow://` via `tauri-plugin-deep-link`, add it to Supabase's redirect allow-list, and handle the callback. Same problem for magic links, email-confirm links and any future OAuth (use PKCE + system browser + deep link, never an embedded login popup).
- **Cloudflare Turnstile** validates the page hostname. A custom origin like `tauri://localhost` may not be allow-listable. Options: for desktop, send users to the web app for "Request Access" and password reset (keep Turnstile where abuse happens: public anonymous endpoints), and let desktop do only password sign-in with Supabase (Supabase-side captcha settings must still be consistent; that is the same open item as Task 35 in the backlog).
- **Token storage.** localStorage in a webview is acceptable for MVP; stronger storage (keychain via a Tauri plugin) is a later hardening.

**CORS**
- Add the desktop origins to `cors_origins`: `tauri://localhost`, `http://tauri.localhost` (and `https://tauri.localhost` depending on config). This is a deliberate widening of the allow-list; keep it behind an env var and test it in the production configuration. CORS is not an auth boundary (auth is the JWT), but restrict it anyway.

**File handling**
- `<a download>` blob downloads and file `<input>` behave inconsistently in webviews; some platforms silently do nothing or save without a dialog. Use Tauri `dialog` + `fs` plugins behind the `platform` service. Also affects report export (`html-to-image` output in `ReportModal.tsx`).

**WebView differences (real, often underestimated)**
- Windows uses Chromium-based WebView2, macOS uses WebKit, Linux uses WebKitGTK. The web build today is effectively only tested in Chromium (Playwright config). Expect CSS and feature differences, and test Safari/WebKit behaviour.
- `html-to-image` relies on SVG `foreignObject`, which is known to be flaky on WebKit (fonts/images missing on first render). The canvas "image export" feature is the most likely to break on macOS/Linux.
- **React Flow performance on WebKitGTK** has historically been weaker than Chromium; the 12-node examples are fine, much larger graphs may not be. Linux also requires `webkit2gtk-4.1`, and Wayland/GPU issues are common; plan for an AppImage plus `.deb`/`.rpm` and document minimum distros.

**Distribution and trust (recurring cost and effort)**
- **macOS:** Apple Developer Program (~$99/year) for signing and notarization; unsigned apps are blocked or warned by Gatekeeper.
- **Windows:** unsigned installers trigger SmartScreen warnings. Options: an OV/EV certificate or a managed signing service (e.g. Azure Trusted Signing, a few dollars/month at the time of writing; verify current eligibility and price).
- **Linux:** no signing gate, but packaging/testing across distros.
- **CI:** you cannot build macOS binaries on Windows. Use a GitHub Actions matrix (`tauri-action`) for Windows, macOS and Linux and publish to GitHub Releases. The repo currently deploys the web via `amplify.yml`; this is a separate pipeline.
- **Auto-update:** `tauri-plugin-updater` needs an update-signing keypair (guard the private key like a production secret) and a hosting location for update manifests.

**Version skew (architectural, not a tooling issue)**
- The web app is always current; installed desktop apps are not. An old desktop client will call a newer backend. Therefore: version the API (`/api/v1`) or at least send an `X-Client-Version` header; have the backend return a "client too old, please update" response; keep backend changes backward-compatible for N versions; add a minimum-version check in the UI. Without this, backend schema changes become risky.

**Product/policy interplay with MVP2.5**
- MVP2.5 intentionally keeps AiFlow *gated, not public*. A publicly downloadable binary is not itself a security problem (access is enforced server-side), but it widens the surface: more rate-limit pressure on unauthenticated endpoints, and the app is easier to analyse. Consider distributing installers only to approved users (links shown after login) or via the landing page with the same "Request Access" CTA.
- Usage limits must stay server-side. They already are (`/users/me/usage`), so keep it that way; never add client-side-only limits for desktop.

**Testing**
- Existing Playwright e2e runs against the web build in a browser. Tauri apps are driven through `tauri-driver` (WebDriver) and it does not support macOS, so full desktop e2e is limited. Practical stance: e2e on web remains the main safety net; desktop gets a small smoke suite plus manual checks per release.

**Maintenance**
- Adds a Rust toolchain, Tauri version upgrades, plugin API churn, and platform-specific bugs to the project. For a solo developer this is real ongoing cost; budget it.

#### 5. "Same db, same access, same features": what that can and cannot mean

- **Same DB and same access: yes**, via the shared backend + Supabase. Nothing extra to build.
- **Same features: yes** for everything the hosted backend does (generate, chat, validate, simulate, evaluate, admin).
- **Offline:** *not* for free. "Same DB" means online-required. Today workflows are saved locally (localStorage/JSON files) as well, so editing without network is plausible, but generate/simulate/evaluate need the backend. If offline matters, you need a local-first sync design (the backlog already mentions localStorage as a write-through cache). Decide this explicitly; it is the biggest scope multiplier.
- **Desktop-only extras break "totally the same"** (local LLM, keychain, file associations). That is fine, and arguably the point, but model them as capability flags on the `platform` service so the UI degrades cleanly on web.

#### 6. Things you may not have thought of

1. **Is a PWA enough?** An installable PWA gives a standalone window on Windows/macOS/Linux (Chromium-based browsers) with no signing, no updater, no CI matrix, and zero version skew. Its limits: no real keychain, no deep-link control, restricted local file access (File System Access API only in Chromium), no local-LLM story without CORS tinkering. If the only goal is "an icon on the desktop", a PWA is 1–2 days and a good experiment to measure whether anyone uses an installed version. Tauri is justified when you want the native extras in §3.4.
2. **Tauri vs Electron.** Electron bundles Chromium: identical rendering on every OS (removes the WebKit risks in §4), at a cost of ~100 MB+ installers and higher memory use, and is the safest choice if rendering parity (React Flow, html-to-image) matters more than size. Tauri is smaller and more secure by default. Given the WebKit risks above, treat this as a real decision, not a given: prototype the canvas and image export in Tauri on macOS and Linux first and decide based on the result.
3. **Sidecar / fully local mode.** Tauri can launch a bundled Python backend (PyInstaller) so the app works with no server. This is feasible but heavy (large binary, antivirus false positives, per-OS builds, auth/DB story diverges since there is no Supabase). It contradicts "same db, same access"; I would defer it, or provide a lighter alternative: desktop connects to either the hosted backend or a user-supplied backend URL.
4. **Local LLM / bring-your-own-key.** The most compelling desktop-only feature for a workflow tool: run simulations/evaluations against Ollama or the user's own key stored in the OS keychain, which also removes your LLM cost. Needs a provider-selection setting; the provider abstraction in `backend/app/providers/` is already isolated. Note that if the LLM call is made from the desktop client directly, the "no keys in the frontend" rule in CLAUDE.md needs a documented exception (user's own key, stored in keychain, never sent to your server) or a local proxy.
5. **Content Security Policy.** Tauri encourages a strict CSP; you must explicitly allow the API host, Supabase, and Cloudflare (if Turnstile loads). Easy to forget and breaks only in the packaged app.
6. **Deep link and single-instance behaviour**: clicking a magic link or a shared workflow must reach the already-running instance (`single-instance` plugin).
7. **Telemetry/analytics.** `useAnalytics.ts` posts events to the backend. Tag the platform (`web` / `desktop-win` / …) and app version so you can see who uses what. Be transparent in the privacy text.
8. **Landing page and SEO assets** (`sitemap.xml`, `robots.txt`, `og-image.svg`, Google verification file) are web-only. The desktop build should skip the landing page and start at login/app.
9. **Routing.** Verify the router mode used in `main.tsx`/`App.tsx`; Tauri serves bundled assets with an SPA fallback so browser-style routing generally works, but verify deep-link and refresh behaviour in the packaged app.
10. **Environment/build matrix.** Introduce explicit Vite modes (`--mode web`, `--mode desktop`) and `VITE_PLATFORM`, `VITE_API_BASE_URL`, `VITE_SUPABASE_*` per mode; don't branch on user agent.
11. **Licensing/legal**: signing certificates, privacy policy text for an installed app, third-party licence notices bundled with the installer.
12. **Release naming and channels**: stable vs beta channel, rollbacks, changelog shown on update. Cheap to design up front, painful later.

#### 7. Recommendation and phasing

I would do it, in this order, stopping at any phase if the results are bad:

| Phase | Work | Exit criterion |
|---|---|---|
| 0. Prep (benefits the web too) | `platform` service abstraction; Vite modes; `/api/v1` or `X-Client-Version` + min-version check; make CORS origins env-driven | Web app unchanged and tests green |
| 1. Feasibility spike (1–2 days) | Minimal Tauri shell for Windows + macOS + Linux pointing at the hosted API; open an example, simulate, export image | Canvas, simulation, and image export work on all three; **decide Tauri vs Electron here** |
| 2. Make it real | Native save/open dialogs; auth flow decisions (system-browser for reset/request-access; deep link); CSP; CI matrix that produces unsigned artifacts | Approved user can log in and complete the core flow on each OS |
| 3. Ship | Code signing (Apple/Windows), updater, versioned release pipeline, gated download link | Installers pass Gatekeeper/SmartScreen; update path tested |
| 4. Desktop-only value | Local LLM / BYOK in keychain, file associations, recent files, optional offline editing | At least one feature that justifies the app over a PWA |

**Optional step before Phase 1:** ship a PWA manifest + service worker for the shell. It is cheap, answers "will anyone install this?", and clarifies which native features users actually miss.

#### 8. Open decisions for you

1. Primary reason for desktop: portfolio polish, native features (local LLM/keychain/files), or offline use? This sets the phasing.
2. Is offline editing in scope, or is online-required acceptable?
3. Who may download installers: anyone, or approved users only?
4. Tauri (small, WebKit risk) or Electron (large, rendering parity): decide after the Phase 1 spike.
5. Is the Apple/Windows signing budget acceptable, or will early builds be unsigned developer previews?
