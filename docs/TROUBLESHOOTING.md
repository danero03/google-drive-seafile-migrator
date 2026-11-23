# Диагностика известных проблем

| Симптом | Причина/действие |
|---|---|
| `Duplicate object found in source` в обычном `rclone copy` | В Google Drive несколько объектов с одним именем в одной папке. Используйте `backend copyid` через v6 и его манифест. |
| `failed to authenticate` у Seafile | Проверить пароль/API-авторизацию, права записи и частоту запросов; уменьшить `--workers`. |
| `Connection refused` у RC-монитора | Процесс `rclone rcd` завершился (в том числе после успешной миграции) или выбран устаревший порт. Сверить терминал основного процесса и `ps`. |
| `Missing file / mismatched size` у старой v5 | Известная проблема сопоставления путей в `operations/list`; использовать v6 `--verify` с `rclone lsjson`. |
| `Existing file not recorded in state; refusing overwrite` | Файл есть, но ID отсутствует в состоянии (возможно, завершение между копией и записью state). Не удалять файл: сверить с манифестом и восстановить состояние контролируемо. |
| `Previously copied file missing or mismatched` | Состояние и назначение разошлись, повторное копирование блокируется во избежание перезаписи. Проверить реальные пути/размеры и сопоставление ID. |
| `429`, `502`, `503`, `504` | Временные ограничения или ошибки API; уменьшить параллелизм, дождаться восстановления, повторить с прежним состоянием. |
| `null` от Google Drive query | Может указывать на пустую папку; проверить неожиданное `null`, особенно для непустого каталога. |
| `--verify` показывает 0 успешно проверенных при видимых файлах | Проверить текущую версию скрипта, отдельные `rclone lsjson`, наличие папки назначения и корректность remotes. |

## Ручная диагностика

```bash
ps -eo pid,etime,stat,%cpu,%mem,cmd | grep -E '[d]rive_to_seafile|[r]clone rcd'
rclone size seafile:GoogleDrive-Import
rclone lsf seafile:GoogleDrive-Import --recursive --files-only | wc -l
```

Проверка OOM в Linux:

```bash
sudo journalctl -k --since '30 minutes ago' | grep -Ei 'out of memory|oom|killed process'
```

**Примечание:** одинаковое количество файлов не доказывает их идентичность. Итоговая сверка делается через `--verify` плюс выборочная проверка содержимого.
