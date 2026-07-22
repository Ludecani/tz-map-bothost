#!/usr/bin/env bash
# One-time helper: write Mail.ru credentials into GitHub Actions repository secrets.
# Requires: gh auth with repo + secrets write (your personal account, not the cloud agent token).
set -euo pipefail

REPO="${REPO:-Ludecani/tz-map-bothost}"
DEFAULT_LOGIN="${MAILRU_LOGIN:-rusakov_751@bk.ru}"

echo "Repository: ${REPO}"
echo "Will set secrets: MAILRU_LOGIN, MAILRU_PASSWORD"
echo "Open later: https://github.com/${REPO}/settings/secrets/actions"
echo

read -r -p "Mail.ru email [${DEFAULT_LOGIN}]: " LOGIN
LOGIN="${LOGIN:-$DEFAULT_LOGIN}"
if [ -z "${LOGIN}" ]; then
  echo "email required" >&2
  exit 1
fi

read -r -s -p "Пароль для внешних приложений (не обычный пароль): " PASS
echo
if [ -z "${PASS}" ]; then
  echo "password required" >&2
  exit 1
fi

printf '%s' "${LOGIN}" | gh secret set MAILRU_LOGIN --repo "${REPO}"
printf '%s' "${PASS}" | gh secret set MAILRU_PASSWORD --repo "${REPO}"

echo
echo "OK. Secrets saved."
echo "Check: gh secret list --repo ${REPO}"
echo "Then run (без формы): https://github.com/${REPO}/actions/workflows/mailru-sync.yml"
echo "Или дождитесь schedule (каждые 10 мин)."
