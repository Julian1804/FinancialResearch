# Morningstar User Action Checklist

1. Manually log in to Morningstar Direct or Analytics Lab.
2. Use Morningstar's UI to Copy Authentication Token.
3. Paste the token into `config/local_secrets.json` under `morningstar.md_auth_token`.
4. Optionally keep `morningstar.account_hint` for human context; do not store passwords.
5. Run the Morningstar safe access smoke test from the FinancialResearch backend environment.
6. Token timing is tracked by `runtime/authoritative_crawler_framework/morningstar_token_state.json`.
7. Refresh the token after it expires, normally after 24 hours.
8. Do not write a Morningstar password into any config file.
9. Do not upload `config/local_secrets.json` or token-bearing files to git.
10. Review entitlement and redistribution terms before any large request or raw storage workflow.
