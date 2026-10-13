# Runtime ASAR bootstrap implementation plan

Consumes Root-approved DESIGN-PLAN.md; no Git writes or extra approvals. Owner scope: desktop/runtime.cjs, new desktop/packaged-bootstrap.test.cjs, this evidence directory. Packaging worker independently supplies byte-identical root/owned-runtime/runtime-bootstrap.cjs.

1. Read Runtime and existing lifecycle/bootstrap tests plus locked @electron/asar3.4.1 types/implementation. Preserve runtime.cjs before bytes.
2. Add actual packed ASAR regression executing archived Runtime code at its canonical archive filename; external Node22 actually resolves/loads the bootstrap and exchanges JSON. Linux Windows/NAPI bridge and Core business fixture are explicitly doubles. Test missing physical script refuses while packed archive still contains bootstrap.
3. Run node --test desktop/packaged-bootstrap.test.cjs and preserve expected exit1/code1/MODULE_NOT_FOUND RED before production change.
4. Change only Windows fork modulePath to path.join(this.root, 'owned-runtime', 'runtime-bootstrap.cjs'). Keep Node, argv, env, generation, native Job and lifecycle logic intact.
5. Run same test GREEN; related desktop runtime, bootstrap, shutdown, quit, cancellation admission checks. Preserve output/exit/SHA/diff; do not rerun full Core/frontend or start real GUI/models/data.
6. Validate own new docs/receipts and exact before-to-after patch reconstruction; return concrete handoff to Root/packaging worker. Final packaged actual Core and GUI checks remain with corresponding owners.
