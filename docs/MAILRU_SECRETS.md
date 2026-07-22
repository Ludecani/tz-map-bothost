# Mail.ru sync credentials

Action `Push sync to Mail.ru folder` uploads `sync-state.json` every 10 minutes.

## Priority

1. Form fields on **Run workflow** (optional)
2. Repository secrets `MAILRU_LOGIN` / `MAILRU_PASSWORD`
3. Built-in cred-blob fallback (used when agent cannot write GitHub secrets)

## Preferred long-term setup

If you have admin access to the repo:

1. https://github.com/Ludecani/tz-map-bothost/settings/secrets/actions
2. **Repository secrets** → `MAILRU_LOGIN`, `MAILRU_PASSWORD`
3. Rotate the Mail.ru app password afterwards (it appeared in older Action logs)

```bash
bash scripts/set_mailru_github_secrets.sh
```
