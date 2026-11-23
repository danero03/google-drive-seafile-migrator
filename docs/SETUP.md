# Настройка окружения и подключений

## Требования

- Linux (проверено на Kali Linux), Python 3.9+, Rclone 1.76+;
- HTTPS-доступ к Google Drive и Seafile;
- право чтения исходной общей папки и право записи в целевую библиотеку;
- достаточная квота на Seafile (исходный набор: 45.681 GiB).

```bash
sudo apt update && sudo apt install -y rclone python3 curl ca-certificates
rclone version
python3 --version
```

## Подключение Google Drive

```bash
rclone config
```

Создайте `gdrive` с типом `drive`, включив OAuth scope **read-only** (`drive.readonly`), и авторизуйтесь в аккаунте, которому открыт доступ к исходной папке. Если папка является обычной опубликованной/расшаренной папкой, а не Shared Drive, не выбирайте режим Shared Drive без оснований. `gdrive:` не обязательно должен указывать на эту папку как на корень: скрипт инвентаризирует её по ID.

Проверка:

```bash
rclone listremotes
rclone backend query gdrive: "'25_E7_5I-1i-UqOzf2UP1JFLOxBa7NGWM' in parents and trashed = false"
```

Ожидается JSON-список объектов (формат выдачи зависит от версии backend). `null` может означать пустую папку, но для корня с данными — повод проверить ID и доступ.

## Подключение Seafile

Сервер в проверенном сценарии: `https://drive.armenianclub.org`.

```bash
rclone config
```

Создайте `seafile` типа `seafile`, укажите адрес сервера, свою учётную запись и пароль/поддерживаемый способ авторизации. Если вход в браузере осуществляется только через SSO, возможно потребуется **локальный пароль Seafile**, если это разрешено администратором.

При настройке библиотеки укажите **Media**. Тогда `seafile:` означает корень библиотеки Media, а `seafile:GoogleDrive-Import` — подпапку внутри неё. Не создавайте remote на уровне всех библиотек, если сценарий ожидает Media.

Проверка:

```bash
rclone lsd seafile:
rclone listremotes
```

См. [шаблон конфигурации](../examples/rclone.conf.example), но не переносите его напрямую в `rclone.conf` без интерактивной настройки через `rclone config`: реальные секреты Rclone хранит/обрабатывает своим способом.

## Проверить доступность источника и назначения

```bash
rclone backend query gdrive: "'25_E7_5I-1i-UqOzf2UP1JFLOxBa7NGWM' in parents and trashed = false"
rclone lsd seafile:
```

Скрипт v6 имеет специальные ограничения: `gdrive:`, `seafile:`, исходный ID `25_E7_5I-1i-UqOzf2UP1JFLOxBa7NGWM`, каталог `GoogleDrive-Import`. При переносе **другой** папки потребуется изменения ограничений и изоляция нового состояния; не пытайтесь обойти проверки случайными параметрами.
