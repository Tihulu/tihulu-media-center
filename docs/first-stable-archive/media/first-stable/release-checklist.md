# TIHULU Media First Stable — Release Checklist

## Pre-Release

- [x] Original binary preserved and verified
- [x] Archive created with integrity verification
- [x] All critical files backed up
- [x] Package scripts created and tested
- [x] Documentation complete
- [x] Dependencies documented

## Pre-Publication

- [ ] Owner authorization for GitHub publication
- [ ] Binary publication authorization (separate from archive)
- [ ] Repository visibility confirmed (private vs public)
- [ ] License compatibility verified
- [ ] No sensitive data in artifacts

## Stable Tag Operations (Requires Separate Approval)

- [ ] Tag name confirmed: `media-stable-v1.0.0`
- [ ] Target commit SHA verified
- [ ] Tag is immutable (no force-push)
- [ ] Release notes drafted
- [ ] Artifact download link verified
- [ ] Rollback documentation tested

## Post-Release

- [ ] Download link tested
- [ ] Installation verified in clean environment
- [ ] Rollback tested
- [ ] Original installation unchanged

## Sign-off

| Role | Status | Name/Date |
|------|--------|-----------|
| Archive Engineer | PASS | Qwen 35B Local / 2026-11-13 |
| Release Engineer | HOLD | Awaiting owner approval |
| QA Manager | HOLD | Clean restore test pending |