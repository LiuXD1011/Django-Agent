# Langfuse development startup design and plan

Root selected the CoreOwner approach in AUTOSTART-GAP.md and authorized ordinary design and fixes. This artifact follows that accepted design. No commit, staging, dependency changes, desktop/frontend changes or legacy deletion.

A lazily used LocalServicesStartupService belongs to CoreApplication. A trusted Node method sends only an absolute sourceRoot over the private Owner channel; HTTP and renderer invoke retain their registered business routes. The service reads one owner-held integration snapshot, extracting only autostart, timeout and API base. Nonempty deployment environment wins; BASE_URL > saved base_url > HOST > localhost default. Tracing enabled and UI URL do not control startup.

Default-off and external API return without cache creation or CLI calls. Enabled loopback startup uses a dedicated dataRoot/.cache/langfuse SQLite database with timeout:0 and BEGIN IMMEDIATE; its OS lock spans the operation and releases on rollback/close or process death. A monotonic 1–120 second deadline covers lock, executable resolution, config, up, health. No stage resets it. Fixed shell-free compose argv run through the existing OwnedProcessRegistry. The resolver preserves missing executable versus access/isolation failures without changing shared process code. Only GET status 200 from the API health path succeeds; native http/https requests use direct agents, no proxy or redirect forwarding.

State is atomically written under the selected dataRoot, excludes secrets/output, and has the old fixed categories plus cancelled. App close aborts startup and waits for owned helpers; compose down is never invoked. Dev CLI installs signal guards before optional work, calls after owner ready and before HTTP listen, then continues business startup after fixed nonfatal results. Desktop never calls this method.

Alternatives considered in the accepted requirement: a second startup database owner adds a credential/consistency path; keeping Python or hiding UI fails complete migration. Neither is used.

Implementation checkpoints:
- [x] Save actual existing-dev RED: isolated administrator saves true, controlled CLI records zero calls and no startup state.
- [x] Add behavioral tests for resolution, early exits, fixed argv, health, failure, cancellation and real cross-process SQLite lock/crash recovery; run RED before implementation.
- [x] Implement service and owner lifecycle wiring, then private call and dev ordering. Trusted fixture executable options exist only in service constructor; no OwnerCall or HTTP executable/env/argv parameters.
- [x] Execute typecheck, focused tests, real dev subprocess protocol and fresh build. Save exits and source SHA; do not repeat unchanged full suite.
- [x] Save REPORT.md and code-complete.diff. Linux fixture evidence is not Docker/Langfuse deployment or native Windows validation. Root coordinates those gates.

All tests use disposable data/source/env and controlled children/loopback ports (port 0). They never invoke Docker, read the real .env.langfuse, use actual credentials/accounts, or manage existing services. Test helpers are stopped through owned handles and their terminal exit is awaited before temporary directories are removed.

The narrow OwnedProcessRegistry discardOutput extension was explicitly authorized by Root after identifying the old discard semantics; see REPORT.md. Deployment, Orca and native Windows gates remain outside code-complete acceptance.
