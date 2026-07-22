# Mail.ru sync secrets

GitHub Action `Push sync to Mail.ru folder` uploads `sync-state.json` into the shared Mail.ru folder.

## One-time setup (recommended)

1. Open [Repository secrets](https://github.com/Ludecani/tz-map-bothost/settings/secrets/actions).
2. Add:
   - `MAILRU_LOGIN` — e.g. `rusakov_751@bk.ru`
   - `MAILRU_PASSWORD` — **пароль для внешних приложений**, not the mailbox password
3. Run the workflow with empty form fields, or wait for the schedule.

Or from a machine where you are logged in as repo owner:

```bash
bash scripts/set_mailru_github_secrets.sh
```

## Fallback

Manual **Run workflow** still accepts email/password in the form if secrets are empty.
