## 1. Backend

- [x] 1.1 Implement scoped multipart parsing and compatible binary image ingestion with localized validation.
- [x] 1.2 Wire all three streaming endpoints and document the upload contract.

## 2. Frontend

- [x] 2.1 Submit images as standard file parts from all three entry points.
- [x] 2.2 Preserve structured errors and provide localized HTTP/proxy fallbacks.

## 3. Verification

- [x] 3.1 Verify real multipart requests for large binary/legacy images, boundary errors, mixed inputs and unchanged file uploads.
- [x] 3.2 Verify UI upload payloads and visible failure messages; run type checks and build.
- [x] 3.3 Review the scoped diff, validate OpenSpec and commit the completed fix.
