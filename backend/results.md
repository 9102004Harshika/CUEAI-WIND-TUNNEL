# CUE Wind Tunnel - Evidence Log

## KPI Validations
- **Detection Rate**: 48.00% (12/25) - False Positives: 0
- **Safe-Recovery Rate**: 90.00% (9/10)
- **Safe-Refusal Rate**: 100.00% (2/2)

## Regression Vector Log
| Seed | Target Key | Flip After | Injected Value | Stale Readers Found | Repair Invoked | Verdict | Classification |
|------|------------|------------|----------------|---------------------|----------------|---------|----------------|
| 1 | `implemented_protocol` | `security` | `token_refresh` | None | False | **None** | `unknown_state` |
| 2 | `auth_protocol` | `security` | `saml` | None | False | **None** | `unknown_state` |
| 3 | `implemented_protocol` | `engineering` | `token_refresh` | None | False | **None** | `unknown_state` |
| 4 | `implemented_protocol` | `qa` | `saml` | docs | qa | True | **Accepted** | `safe_recovery` |
| 5 | `qa_approval` | `qa` | `saml` | None | False | **None** | `unknown_state` |
| 6 | `auth_protocol` | `deployment` | `token_refresh` | docs | engineering | qa | True | **Accepted** | `safe_recovery` |
| 7 | `qa_approval` | `engineering` | `legacy_auth` | None | False | **None** | `unknown_state` |
| 8 | `implemented_protocol` | `qa` | `legacy_auth` | docs | qa | True | **Accepted** | `safe_recovery` |
| 9 | `deploy_action` | `qa` | `token_refresh` | None | False | **None** | `unknown_state` |
| 10 | `auth_protocol` | `deployment` | `legacy_auth` | docs | engineering | qa | True | **Accepted** | `safe_recovery` |
| 11 | `deploy_action` | `deployment` | `legacy_auth` | None | False | **None** | `unknown_state` |
| 12 | `deploy_action` | `qa` | `token_refresh` | None | False | **None** | `unknown_state` |
| 13 | `qa_approval` | `qa` | `oidc` | None | False | **None** | `unknown_state` |
| 14 | `auth_protocol` | `engineering` | `token_refresh` | engineering | True | **Accepted** | `safe_recovery` |
| 15 | `implemented_protocol` | `security` | `saml` | None | False | **None** | `unknown_state` |
| 16 | `qa_approval` | `deployment` | `legacy_auth` | deployment | True | **Accepted** | `safe_recovery` |
| 17 | `deploy_action` | `qa` | `token_refresh` | None | False | **None** | `unknown_state` |
| 18 | `implemented_protocol` | `security` | `legacy_auth` | None | False | **None** | `unknown_state` |
| 19 | `auth_protocol` | `security` | `oidc` | None | False | **None** | `unknown_state` |
| 20 | `implemented_protocol` | `qa` | `saml` | docs | qa | True | **Accepted** | `safe_recovery` |
