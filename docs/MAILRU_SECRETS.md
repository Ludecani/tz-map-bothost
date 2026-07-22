# Mail.ru sync secrets

GitHub Action `Push sync to Mail.ru folder` uploads `sync-state.json` into the shared Mail.ru folder.

## One-time setup (required for schedule)

1. Open **Repository** secrets (not Environments):
   https://github.com/Ludecani/tz-map-bothost/settings/secrets/actions
2. Click **New repository secret** and add exactly these names:
   - `MAILRU_LOGIN` — e.g. `rusakov_751@bk.ru`
   - `MAILRU_PASSWORD` — пароль для внешних приложений (не обычный пароль ящика)
3. Run workflow with empty form fields, or wait for schedule (every 10 min).

Or from a machine where you are logged in as repo owner:

```bash
bash scripts/set_mailru_github_secrets.sh
```

## Checklist if Action still skips

- Secrets are under **Actions** → **Repository secrets**, not **Environment secrets**
- Names match exactly: `MAILRU_LOGIN`, `MAILRU_PASSWORD` (case-sensitive)
- Values have no leading/trailing spaces
- You are in repo `Ludecani/tz-map-bothost`

## Fallback

Manual **Run workflow** still accepts email/password in the form if secrets are empty.
