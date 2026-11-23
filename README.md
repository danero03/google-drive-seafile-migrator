# Google Drive → Seafile Migrator

Перенос файлов из **общей Google Drive-папки** в библиотеку **Seafile** через Rclone и Python с сохранением объектов, имеющих одинаковые имена в Google Drive.

> **Проверенный сценарий:** Kali Linux, Python 3.9+, Rclone 1.76.0, Seafile 13.0.25. Итог прошлого переноса: **6 604 файла**, **45.681 GiB**, **59 коллизий имен**, проверка путей и размеров прошла с `errors=0`.
>
> **Ограничение текущей версии:** v6 специально ограничена папкой Google Drive с ID `25_E7_5I-1i-UqOzf2UP1JFLOxBa7NGWM`, целевым каталогом `GoogleDrive-Import`, remotes `gdrive:` и `seafile:` (настроенным на библиотеку Media). Для другой папки/библиотеки необходимо сначала адаптировать защитные проверки в скрипте. Это не универсальная настройка одной CLI-опцией.

## Структура

```text
google-drive-seafile-migrator/
├── README.md
├── LICENSE
├── .gitignore
├── scripts/
│   ├── drive_to_seafile_all_v6.py   # --plan, --run, --verify
│   └── rclone_monitor.py            # дополнительный монитор RC
├── examples/
│   └── rclone.conf.example          # только шаблон, без секретов
├── docs/
│   ├── SETUP.md                     # настройка Google Drive и Seafile
│   ├── OPERATIONS.md                # перенос, возобновление, верификация
│   ├── TROUBLESHOOTING.md           # известные проблемы
│   └── SECURITY.md                  # правила безопасного использования
└── tests/
    └── test_manifest.py            # тесты, не требующие подключений
```

## Быстрый старт

Установить Rclone и Python:

```bash
sudo apt update
sudo apt install -y rclone python3 curl ca-certificates
rclone version
python3 --version
```

Настроить `gdrive:` с Google Drive **read-only OAuth**, а `seafile:` — на **корень библиотеки Media**, см. [SETUP.md](docs/SETUP.md). Не копируйте из чужих инструкций токены или пароли.

```bash
rclone listremotes
rclone lsd seafile:
# Чтение содержимого исходной папки по ID:
rclone backend query gdrive: "'25_E7_5I-1i-UqOzf2UP1JFLOxBa7NGWM' in parents and trashed = false"
```

```bash
# ВНИМАНИЕ: команды рассчитаны на свежую миграцию или на продолжение
# с теми же manifest.json и state_v5.json.
python3 scripts/drive_to_seafile_all_v6.py --plan
python3 scripts/drive_to_seafile_all_v6.py --run --workers 4 --request-delay 0.5 --retries 7 --retry-wait 10
python3 scripts/drive_to_seafile_all_v6.py --verify
rclone size seafile:GoogleDrive-Import
rclone lsf seafile:GoogleDrive-Import --recursive --files-only | wc -l
```

Если плана нет, `--run` и `--verify` умеют формировать его автоматически. **Повторно вызывать `--plan` для уже созданного манифеста необязательно**.

Последний успешный результат исходной миграции:

```text
Finished: copied=0, verified=6604, errors=0, unsupported=0
SUCCESS: all expected paths and reported sizes matched.
```

Это проверка **путей и размеров**, а не криптографических хешей или идентичности содержимого. Перед удалением оригинала откройте вручную выборку фотографий и видео, включая крупные файлы.

## Повторный запуск и данные состояния

По умолчанию создается каталог `~/rclone-migration-duplicates/`:

- `manifest.json` — уникальные Drive ID, конечные пути, размеры, каталогизация, переименованные коллизии;
- `state_v5.json` — прогресс, совместимый с предыдущей v5;
- `errors_v6.json` — ошибки текущего запуска/проверки.

**Эти файлы намеренно исключены из Git.** При новой независимой миграции используйте новое значение `--workdir` и пустую целевую директорию. Не удаляйте состояние работающей миграции и не перезаписывайте уже существующие файлы без сверки.

```bash
# Продолжение после прерывания — те же файлы состояния и параметры:
python3 scripts/drive_to_seafile_all_v6.py --run --workers 4 --request-delay 0.5 --retries 7 --retry-wait 10
```

Если копирование файлов закончилось, а монитор стал выдавать `Connection refused`, это **может быть нормальным завершением**: дочерний RC-сервер останавливается вместе со скриптом. Сначала проверьте основной лог.

Документация: [настройка](docs/SETUP.md) · [порядок действий](docs/OPERATIONS.md) · [решение проблем](docs/TROUBLESHOOTING.md) · [безопасность](docs/SECURITY.md).

## Запуск тестов

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
```

## Публикация на GitHub

Архив включает **код, документацию и безопасный пример конфигурации**, но **не** реальный `rclone.conf`, токены OAuth, манифест, состояние или логи с именами пользовательских файлов.

```bash
git init
git add .
git status
git commit -m "Initial Google Drive to Seafile migrator"
# Создайте пустой репозиторий на GitHub, затем:
git branch -M main
git remote add origin https://github.com/USERNAME/google-drive-seafile-migrator.git
git push -u origin main
```
