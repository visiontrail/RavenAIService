## 1. Implementation

- [x] 1.1 Vendor the pinned upstream skill, license, provenance and technical response prompt.
- [x] 1.2 Integrate mandatory materialization, per-run prompt loading and truthful trace events in both Agents.
- [x] 1.3 Preserve optional skill selection and structured response validation; document the contract.
- [x] 1.4 Include the referenced login/register backdrop fix.

## 2. Verification and delivery

- [x] 2.1 Cover empty data, follow-ups, relevance limits, overrides, failures and both Agent request paths; run regression checks.
- [x] 2.2 Commit and push the reviewed service changes and parent gitlink.
- [x] 2.3 Deploy the exact commit to nr-test and verify real Agent turns, trace evidence and login/register UI. Code commit: `762a54f`; 2026-09-10 validation: 103 backend tests, 34 frontend tests, type-check and build passed. Both Agents completed an initial question and follow-up, each with one `required_skill_loaded` / `server_prompt` event and the pinned source digest. Production login (2 fields) and registration (5 fields) retained input after backdrop clicks; close/cancel remained functional. Backend/worker/frontend healthy; running source hashes matched the checkout.
