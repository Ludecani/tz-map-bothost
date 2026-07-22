# Mail.ru sync secrets

## Куда именно нажимать

1. Откройте: https://github.com/Ludecani/tz-map-bothost/settings/secrets/actions
2. Вкладка **Secrets** (не Variables, не Environments, не Dependabot)
3. Блок **Repository secrets** → **New repository secret**
4. Создайте два секрета с именами **точно**:
   - Name: `MAILRU_LOGIN`  
     Secret: `rusakov_751@bk.ru` (или ваша почта)
   - Name: `MAILRU_PASSWORD`  
     Secret: пароль **для внешних приложений** (не обычный пароль ящика)

После этого Action без формы должен писать в лог `MAILRU_LOGIN=Y MAILRU_PASSWORD=Y`.

## Если снова N / N

- Вы в другом разделе (Environment / Variables / Dependabot)
- Имя с опечаткой или лишним пробелом
- Секрет создан в другом репозитории

Пока secrets не видны — используйте **Run workflow** с полями формы (это уже работает).
