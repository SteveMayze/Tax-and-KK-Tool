# PHASES_2.md: Tax and Healthcare Tool, Phases 9 to 14

Save this file as `docs/prompts/PHASES_2.md`.
**Do not edit or overwrite `docs/prompts/PHASES.md`.** It documents Phases 1 to 8 and is kept for audit. If you find an error in it, record it in your end-of-phase report instead.

## Standing rules for every phase below

1. Read first: `CLAUDE.md`, `docs/prompts/PHASES.md`, `docs/rules/`, `docs/decisions/` (ADRs), `docs/deployment.md`. Everything in `CLAUDE.md` still applies (Decimal only, keep originals, state the basis of every figure, never guess a legal or SBK rule, no real network in tests, synthetic test data only).
2. Work on **one phase at a time**. At the end of a phase: stop, give the end-of-phase report (what was done, commits, tests added, deviations, open questions, anything not verified), and wait for the owner to say "go" for the next phase.
3. **Ask first.** Each phase lists "Questions for the owner". Ask them in your first reply, together with what you found when you checked the current state. If the owner has not answered, use the stated default, say so at the top of your work, and continue.
4. **Verify the current state.** This file was written from the Phase 1 to 8 feedback report, not from the code. Where a phase says "verify", read the code and say what you found before changing anything. If the code differs from what this file assumes, say so and adapt; do not force the file's assumption onto the code.
5. **Acceptance criteria** are checkable statements. Each one needs a test or a demonstrated command. Report each as met, not met, or not verifiable here, with the evidence.
6. At least one test per feature must exercise the real artifact (the real archive, the real rendered page, the real migration), not a text copy of the code under test.
7. After the owner's decisions in a phase, update `CLAUDE.md` in the same phase so it matches (it currently has known inconsistencies, see Phase 9) and add or supersede an ADR in `docs/decisions/`. Never delete an old ADR; mark it superseded.
8. Anything touching deployment: rehearse before the real deploy (`ansible-playbook --check`, a local container build if a runtime exists, a throw-away check of the generated Quadlet unit). Say clearly which steps only the owner can run (they need the sudo password) and give the exact commands.
9. Nothing in the app is a tax calculation or an SBK assessment. Keep every output labelled as it is today.

---

## Phase 9: Foundation (housekeeping and sub-path readiness)

Goal: remove dead UI, make `CLAUDE.md` truthful, and make the app able to run under the URL prefix `/tax-healthcare` behind a reverse proxy, so the separate gateway repo can serve it over HTTPS. This phase does **not** configure Caddy and does **not** change the deployed port.

### Questions for the owner
- Confirm the URL prefix: `/tax-healthcare`. (Default: yes.)
- Is the app also to stay reachable on its own port 8889 during the transition? (Default: yes, until the gateway works; the closing of the port is a later, separate step in the gateway track.)

### Tasks
1. **CLAUDE.md consistency pass.** Fix these known inconsistencies and any others you find: the path `doc/prompts/PHASES.md` (real path `docs/prompts/PHASES.md`); the Imports section still describing per-institution profiles (the owner decided on one documented CSV format); the display-currency text. Add a short owner profile section with each item marked confirmed or unconfirmed (employment status, children, spouse, sick-pay entitlement), using only facts already recorded in the repo; do not invent any. Add a "Phases 9 to 14" pointer to this file.
2. **Remove the display-currency dropdown** from every page. Remove the session-stored display currency, its view and form code, and its tests. Supersede the relevant ADR or note. Amounts keep showing in their own currency, and reports stay EUR. Verify there is no remaining reference (templates, forms, session, docs).
3. **Prefix support.** Make the prefix configurable by environment variable (default empty, so local development is unchanged). With a prefix set: `FORCE_SCRIPT_NAME` is the prefix; every generated URL, redirect, `LOGIN_URL`, `LOGIN_REDIRECT_URL` and static URL includes it; the app itself still answers when the proxy strips the prefix. Add `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` (only when an env switch says the app is behind a TLS proxy), configurable `CSRF_TRUSTED_ORIGINS` and `ALLOWED_HOSTS`. Do not enable HSTS yet; add a setting that defaults to off and document why (the local CA must be installed on every device first).
4. **Cookies.** Give this app its own session and CSRF cookie names (for example `taxhc_sessionid`, `taxhc_csrftoken`) and set the cookie paths to the prefix when one is configured. Reason: browsers share cookies across ports and paths on one host, and parts-db would otherwise log this app out and the reverse.
5. **Static files.** Verify how static files are handled in production today (the report says static files are off because pages use inline styles). Add WhiteNoise (or an equivalent already-approved approach) so a stylesheet can be served from the app under the prefix in production. Pin the dependency. The admin stays off.
6. **Deployment settings.** Add `listen_address` handling and the new environment variables to the Ansible variables, the Quadlet template and `docs/deployment.md`. Rehearse with `--check`. Do not deploy. (The deployment stays rootful in this phase; Phase 9A converts it to rootless, so keep the variables and templates easy to move.)

### Acceptance criteria
- No page contains a currency dropdown, and `grep -ri "display_currency"` (or the actual name) over the code and templates finds nothing except in superseded ADR text.
- With the prefix set to `/tax-healthcare` in the test settings, a test using the real test client with `SCRIPT_NAME` set logs in, follows redirects, loads a report, and every link and form action on those pages starts with the prefix.
- The two cookie names differ from Django defaults; a test asserts their names and paths.
- A test fetches a static file through the production settings and under the prefix.
- With the prefix empty, the full existing test suite passes unchanged (except the removed dropdown tests).
- `CLAUDE.md` contains none of the three known inconsistencies.
- `ansible-playbook --check` passes for the changed playbooks; the owner's deploy commands are listed.

### Stop and report

---

## Phase 9A: Rootless Podman (deploy without the sudo password)

Added after the first version of this file. It follows Phase 9 and comes before the gateway track builds its Caddy container, because the gateway should use the same model. Phases 10 to 14 are unchanged.

### Why this phase exists (plain language)
The owner assumed the app ran "rootless" and does not need the sudo password for deployment. The Phase 8 feedback report says the opposite: the app runs as a **rootful** Podman container managed by Quadlet system units, and every deploy needs `-K` (the sudo password). The owner has little Podman experience, so **every explanation in this phase, in the docs and in the reports, must assume the reader knows nothing about Podman, containers, systemd or Quadlet.** Define each term the first time it is used, give each command with a one-line "what this does", and say what the owner will see if it works and what to do if it does not.

Short version of the concepts, to be expanded in the docs:
- A **container** is a packaged copy of the app that runs isolated from the rest of the server. **Podman** is the program that runs containers.
- **Rootful**: Podman itself runs as the all-powerful `root` user. Starting, stopping or deploying then needs `sudo`. If something escaped the container it would be root on the server.
- **Rootless**: Podman runs as an ordinary Linux user. No `sudo` is needed to deploy or restart. The container's "root" is mapped to that ordinary user, so an escape would only reach what that user can reach.
- **Quadlet** is a way to describe a container in a small file so that **systemd** (the server's service manager) starts it at boot and restarts it if it fails. Rootful units live in `/etc/containers/systemd/` and need root to change. Rootless units live in the service user's home folder, `~/.config/containers/systemd/`, and are managed with `systemctl --user`.
- **Linger** is a setting that lets a user's services keep running when nobody is logged in, and start at boot. Rootless containers need it.

### Questions for the owner
Ask these in the first reply, in plain language, with the default.
1. **Which Linux user runs the containers?** Default: a new dedicated user `homeapps` with no password login (SSH key only), later shared by the tax app, the gateway and optionally parts-db. Alternative: the owner's own login user (simpler, less isolated).
2. **Is one last use of sudo acceptable?** Setting up a rootless user needs root once (create the user, allow it to keep running when logged out, one system setting). After that, deploys need no sudo. Default: yes, through one clearly labelled bootstrap playbook the owner runs once.
3. **Cut-over method.** Default: build the rootless copy next to the running rootful one on a different port, load a fresh backup into it, let the owner check it, then switch. The rootful container and its data stay untouched until the owner says remove them.

### Tasks
1. **Plain-language guide.** Write `docs/podman-explained.md` for a reader with no Podman knowledge: the concepts above, a picture of "before" (root runs Podman, sudo for every step) and "after" (ordinary user runs Podman, no sudo), a glossary, the daily commands (`make deploy`, `make status`, `make backup-now`, `make rollback`) each with what it does and what normal output looks like, and a troubleshooting section with the likely failures from this phase.
2. **Inspect the server read-only** and report what exists: Podman and systemd versions; whether the current container is rootful and where its unit lives; which user the Ansible connection uses and why it needs `become`/`-K`; storage and volume locations and their owners; whether `/etc/subuid` and `/etc/subgid` have ranges for the chosen user; whether linger is on; the value of `net.ipv4.ip_unprivileged_port_start`; whether cgroup v2 controllers (memory, cpu) are delegated to user sessions; SELinux state; how the daily backup and its timer are run today. Change nothing.
3. **Design and ADR** in `docs/decisions/`: rootless user model, where data lives, how it is backed up, how the container reaches other containers, what still needs root and why. This supersedes the "rootful Podman with Quadlet" decision in ADR 0005; mark ADR 0005 superseded in part, do not delete it.
4. **One-time bootstrap playbook** (`infra/bootstrap-rootless.yml`, with `make bootstrap-rootless`): the only step that uses sudo. It creates the user (no password login), authorises the owner's SSH key, ensures subuid/subgid ranges, enables linger, installs missing packages (Podman, and the rootless networking helper Podman 5 uses, `passt`/`pasta`) and creates the directories. Every task has a comment saying what it does and why. It must be idempotent and `--check` clean. It must **not** contain the app, a secret, or a firewall change.
5. **Convert the deployment to rootless.**
   - Move the Quadlet container unit to the service user's `~/.config/containers/systemd/` and manage it with `systemctl --user`.
   - Keep today's hardening: non-root user inside the container, read-only root file system, dropped capabilities, no new privileges, health check, resource limits. If a limit cannot be applied in a user session (controller not delegated), report it; do not silently drop it.
   - Make the database and uploads writable by the container user (user-namespace mapping, for example `UserNS=keep-id` or an explicit mapping). State the chosen mapping and show the resulting owner of the data files.
   - Build the image as the service user. Keep "deploy exactly the committed revision (git archive from the repository root, check the unpacked files)".
   - Turn the daily backup into a systemd **user** timer and confirm it fires without anyone logged in.
   - The Makefile and playbooks connect as the service user over SSH and use **no** `become`, no `-K`, no sudo. Where a step truly needs root (only the bootstrap, and the final removal of the old rootful setup), say so explicitly.
6. **Migrate.** Per the owner's cut-over answer: start the rootless instance on a trial port, restore the latest backup into it using the existing restore flow, compare record counts and a checksum of the data with the rootful instance, ask the owner to log in and look. On approval, stop the rootful unit (one last sudo, exact command given), start the rootless one on the real port, run the health check. Leave the old rootful data in place and give, but do not run, the exact removal commands for later.
7. **Rehearse** everything that can be rehearsed: `ansible-playbook --check`; run the real Quadlet generator in dry-run mode on the rendered files (`/usr/lib/systemd/system-generators/podman-system-generator --user --dryrun`, or the equivalent on this system) and show its output; render templates with Ansible's own engine. List what only the real host can prove.

### Acceptance criteria
- After the one-time bootstrap, `make deploy`, `make status`, `make backup-now`, `make restore-drill`, `make fetch-backup` and `make rollback` all run without a sudo password. A test over the real Makefile and playbooks finds no `-K`, `become` or `sudo` outside the bootstrap and the documented removal step.
- On the host, `podman ps` as the service user shows the app container, and the container's processes are owned by the service user (or its subordinate IDs), not by `root` (command and expected output are given to the owner).
- The container is healthy, `/health/` returns 200, the app survives a `systemctl --user restart` and, as verified by the owner, a reboot of the server with nobody logged in.
- The backup timer is a user timer and its next run is shown by `systemctl --user list-timers`.
- Record counts and the data checksum match between the rootful and rootless instances before cut-over.
- `docs/podman-explained.md` exists and every command in it has a one-line explanation. A test fails if the Makefile gains a target that is not documented there.
- ADR written; `CLAUDE.md` updated (deployment section, "no sudo for routine deploys").

### Stop and report
In the report, say in plain language what changed on the server, what the owner can now do without sudo, what still needs sudo and why, and how to go back to the rootful setup.

---

## Phase 10: Income breakdown (gross = net + withholding tax + expenses)

Goal: make the difference between gross and net a first-class, explained quantity.

### Questions for the owner
- Strictness: must gross equal net + withholding + expenses exactly for new and edited payments? (Default: yes, enforced on save; existing payments keep their gap and show it as "unallocated" until edited.)
- Should recorded expenses feed the SBK estimate's manual annual-costs input? (Default: no. Show recorded expenses next to the manual costs as information only.)
- Which categories commonly have expenses or withholding tax? (Used only to decide default visibility of the fields; default: show the fields for every category.)

### Tasks
1. **Verify** how gross, net and the EUR amounts are stored today (original currency at 4 decimals, rate at 10, EUR at 6) and how the conversion audit trail works.
2. **Model.** Add `withholding_tax` and `expenses` to the payment, in the payment's original currency, non-negative, default 0, same precision rules as the other amounts. Add a computed `unallocated = gross - net - withholding_tax - expenses`. Decide with the existing rules how a payment with only gross (no net) behaves; document it.
3. **Validation.** Enforce the invariant for new and edited payments per the owner's answer. The error message must show the three numbers. Corrections and reversals keep working with signed amounts.
4. **EUR conversion.** Convert each new amount with the payment's own recorded rate, in the same audit trail and provenance, at full precision. Never re-convert with a different rate. State in the docs how rounding is handled (round once at report totals, as today).
5. **Migration.** Existing rows get 0 for both new fields. Do not guess a breakdown. Verify the migration on a copy of a realistic database and keep it reversible.
6. **Forms and lists.** Add the two fields to the payment form with a live "unallocated" display, and show them in the payment list and detail. Keep the manual-rate flow working.
7. **Reports and CSV.** Add columns for withholding tax, expenses and unallocated to the reports where gross and net appear, with the basis block explaining the identity. Bump the CSV report format version and keep formula-injection-safe export.
8. **Imports.** Extend the single documented CSV format with optional `withholding_tax` and `expenses` columns. Old files without them still import. Update `docs/` and the preview screen.
9. **Tax and SBK outputs.** Do not change any calculation. Show withholding tax as information in the tax summary and label it "not credited: treaty and foreign-tax-credit rules are not implemented". Record in `docs/rules/` the open question of how withholding tax and expenses should affect SBK and tax figures.

### Acceptance criteria
- A user can save a payment with gross 1000.00, net 800.00, withholding 150.00, expenses 50.00 (any currency) and sees unallocated 0.00; gross 1000.00, net 800.00, withholding 0 and expenses 0 is refused with a message showing the three numbers.
- The EUR values of the new fields use the same rate record as the payment, verified by a test that compares rate ids.
- An existing payment (migrated) opens, shows its unallocated difference, and can be saved unchanged only if the owner's strictness answer allows it; the behaviour is tested.
- A test round-trips an import file with and without the new columns.
- Every changed report shows the new columns on screen and in the CSV, with the identity stated in the basis block.
- The migration applies to and reverses from a copy of a real-shaped database.

### Stop and report

---

## Phase 11: Capital loss

Goal: let a capital loss be recorded and shown correctly, without inventing any loss-offset rule.

### Questions for the owner
- Which categories may hold a loss? (Default: the capital-income categories and the "private sale" category, via a category flag "may be negative".)
- Is there an SBK or tax-office statement on how losses are treated for health-insurance contributions? (Default: none; stays unverified.)

### Tasks
1. **Verify** whether the payment model, forms, importer and reports accept negative normal payments today, and what the SBK estimate does with a negative annual surplus (the report says: counts as 0, no loss netting).
2. Add a category flag "may be negative". Only flagged categories accept a negative gross for a normal payment; all others still refuse negative amounts. Keep corrections and reversals as they are.
3. Reports show the loss signed. Category totals are signed sums. The annual summary shows gains and losses separately and the net per category.
4. SBK estimate: keep the floor at 0 for a negative annual surplus, and make the basis block say, in a run-specific note, that a loss was recorded and not netted or carried over.
5. Tax summary: show losses separately and do not net them across categories. Add to `docs/rules/` an entry "loss offset rules" with status **unverified**, listing the questions (loss pots, carry-forward, relation to SBK). Do not implement anything from memory.
6. Import: allow negative amounts only for flagged categories, with a clear row error otherwise.

### Acceptance criteria
- Entering -500.00 in a flagged category saves; in an unflagged category it is refused with the category named.
- The annual summary shows the loss as a negative figure and the SBK basis block contains the "not netted" note when a loss is present, verified by a test.
- The SBK monthly estimate for a year whose capital surplus is negative equals the estimate with capital income 0.
- `docs/rules/` contains the new unverified entry.

### Stop and report

---

## Phase 12: Language and locale (English default, German reports)

Goal: a language setting that drives the interface language and the number and date formats; German reports and CSV; no invented German legal terms.

### Questions for the owner
- One setting for the whole app (default) or a separate setting for reports? (Default: one setting.)
- German CSV format: semicolon and decimal comma when German is selected? (Default: yes; English CSV unchanged.)
- Please review the German glossary produced in step 1 before step 3 starts. Stop after step 1 and wait for the owner.

### Tasks
1. **Glossary first.** Create `docs/glossary.md` (or a data file) as the single source for report headings and terms in English and German, starting with the 14 report column terms: Employment, Pension, Self-employed, Rental, Capital, One-off (1/12), Base before limits, Assessed base, Limit applied, Health: general part, Health: additional contribution, Health total, Care insurance, Total contribution. For each: English label, German label, one-paragraph explanation, source (a file under `docs/rules/` or an SBK page the repo already cites), and status (verified or "proposed, needs owner review"). Mark every German label that is not taken from an SBK or statute text as proposed. **Stop here for owner review.**
2. **Infrastructure.** Enable Django i18n and locale middleware. Add a language field to the single settings row (English default, German) and a selector in the page header that also takes effect immediately for the session. Generate and commit the `.po` files; compile `.mo` at build time and check that the container build includes them.
3. **Formats.** Numbers and dates follow the selected locale (thousands and decimal separators, date order). Amounts show their ISO currency code after the number, in their own currency; nothing is converted. Reports remain EUR.
4. **Reports.** Translate all eight reports: titles, column headings, basis blocks, notes and labels such as "NOT confirmed with SBK". Use the glossary strings, not ad hoc translations.
5. **CSV export.** Headers and numbers follow the selected language per the owner's answer. Keep formula-injection protection. Include the language and format in the CSV basis block.
6. **Rest of the interface.** Translate navigation, forms, buttons, messages and validation text. Anything not yet translated falls back to English and is listed in the report.
7. **Tests.** A test per report in both languages comparing rendered headings with the glossary; a test that switching the setting changes the format of a known amount and date; a test that no template contains an untranslatable hard-coded string in the report pages (check the real rendered output, not the template text).

### Acceptance criteria
- With German selected, every heading, number and date on the eight reports is German or German-formatted; 1234.5 renders as 1.234,50 and the same amount in AUD keeps the code AUD.
- Switching back to English restores today's output exactly (existing report tests still pass).
- Every German term on report pages appears in the glossary, with its status.
- The built container image contains the compiled translations (verified with a local build, or marked not verifiable here with the exact check for the owner).

### Stop and report

---

## Phase 13: Visual refresh, report layout and information popups

Goal: a consistent blue/teal interface with proper buttons and comfortable inputs; descriptive text under the report output; an information popup on each tax and health-insurance column heading.

### Questions for the owner
- Do you want a dark mode? (Default: no.)
- Which pages are used most? (Default: payments list and entry, reports; polish these first.)

### Tasks
1. **Design tokens.** One stylesheet with CSS variables: a blue/teal palette (primary teal, deeper blue for headings and focus, neutral greys, clear success, warning and danger colours). Text contrast at least WCAG AA. Replace inline styles with classes. Serve the stylesheet through the static setup from Phase 9 and confirm it works under the prefix.
2. **Buttons instead of links** for actions: add, edit, save, cancel, export, recalculate. Plain links remain for navigation between pages. Anything that changes data or deletes must be a POST form button, never a link. Consistent primary, secondary and danger styles.
3. **Inputs.** Text inputs have a sensible minimum width (for example 20 characters, wider for names and descriptions). Note and description fields become text areas about 4 rows high that grow with content and accept a small paragraph (check the model field length allows it, and migrate if not). Selects and date fields get matching sizes.
4. **Report layout.** On all eight reports, move the descriptive block that now sits at the top to below the report table and its totals. The basis block stays directly with the table (it states what the numbers mean) unless the owner says otherwise; confirm this choice in your first reply.
5. **Information popups.** For each of the 14 headings in the glossary, add an info icon (i) next to the heading text. It is a real `<button>` with an accessible name, reachable by keyboard, opening a native `<dialog>` or Popover API element, closable with Escape, working without custom JavaScript where the platform allows. The content is the glossary entry in the selected language, including its source and status. Do not add explanations that are not in the glossary; if a heading has none, add it to the glossary as "proposed" first.
6. **CSV and print.** The (i) icons and popups must not appear in the CSV export. Check that the printed page still shows the table and the text below it.

### Acceptance criteria
- The rendered pages contain no `style=` attributes (test over the real rendered pages of the main screens).
- Contrast of text on every colour pair in the stylesheet meets 4.5:1 (script in the repo that checks the tokens).
- Each of the 14 headings has a focusable info button; Escape closes the popup; the popup text equals the glossary entry (test).
- On every report the descriptive text appears after the table in the document order (test on rendered HTML).
- A "delete" or "recalculate" action cannot be triggered by a GET request (test).
- The payment note field accepts at least 500 characters and renders on 4 rows at least.

### Stop and report

---

## Phase 14: PDF extraction with review (gated)

Gate: do not start until the owner has supplied at least two real sample PDFs with personal details blacked out. If none are available, report that and stop.

### Questions for the owner
- What kind of PDFs? (statements, payslips, rental statements; text-based or scanned?)
- Library: pypdf was proposed earlier. Confirm it, or choose another; scanned PDFs and OCR are out of scope unless the owner says otherwise.

### Tasks
1. Inspect the samples and report what text can be extracted and where the structure is irregular. List the corner cases found before writing any parser.
2. Implement text extraction for the supported layouts only. Unrecognised layouts fail with a clear message and offer manual entry; never guess a value.
3. Feed results into the existing import staging (per-row edit and exclude, duplicate rule, atomic idempotent commit, history, protected original-file download). Mark each extracted field with where it came from in the PDF so the owner can check it.
4. Include the new withholding tax and expenses fields where the layout provides them; leave them empty otherwise.
5. Update `CLAUDE.md` (imports section) and add an ADR.

### Acceptance criteria
- Each sample PDF produces a staging preview matching figures worked out by hand (listed in the test file).
- A PDF with an unknown layout produces an error and no staged rows.
- Nothing is saved until the owner confirms the preview, and a double submit is harmless.
- No real data or PDF content is committed; tests use synthetic PDFs generated in the test suite.

### Stop and report
