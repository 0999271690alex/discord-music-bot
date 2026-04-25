# Discord Music Bot

Discord бот для відтворення музики з YouTube у голосових каналах. Підтримує черги, плейлисти, керування гучністю та інше.

## Можливості

- Відтворення треків з YouTube за URL або назвою
- Підтримка плейлистів — додає всі треки одразу
- Черга з відображенням позицій і тривалості
- Перемішування, очищення, видалення окремих треків
- Пауза, продовження, пропуск, регулювання гучності
- Embed-повідомлення з обкладинкою та тривалістю треку
- Slash-команди (`/play`, `/queue` і т.д.)
- Автоматичне перепідключення до стріму при обриві

## Команди

| Команда | Опис |
|---|---|
| `/play <назва або URL>` | Грати трек або додати до черги |
| `/queue` | Показати чергу (перші 15 треків) |
| `/nowplaying` | Показати поточний трек |
| `/skip` | Пропустити поточний трек |
| `/pause` | Поставити на паузу |
| `/resume` | Продовжити відтворення |
| `/stop` | Зупинити і відключити бота з каналу |
| `/shuffle` | Перемішати чергу |
| `/clear` | Очистити чергу |
| `/volume <0–100>` | Змінити гучність |
| `/remove <номер>` | Видалити трек з черги за номером |

## Вимоги

- Python 3.10+
- FFmpeg
- Бібліотеки: `discord.py[voice]`, `yt-dlp`, `PyNaCl`

## Встановлення

```bash
git clone https://github.com/your-username/discord-music-bot.git
cd discord-music-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Запуск

```bash
export DISCORD_TOKEN="ваш_токен_тут"
python3 bot.py
```

Бот автоматично синхронізує slash-команди при запуску.

## Деплой на сервер (Proxmox LXC)

Детальна інструкція з налаштування на Proxmox LXC контейнер описана у [SETUP.md](SETUP.md).

Коротко:
1. Створити Ubuntu 22.04 LXC контейнер (512 MB RAM, 4 GB диск)
2. Встановити `python3`, `ffmpeg`, `git`
3. Скопіювати файли та налаштувати virtualenv
4. Вставити токен і запустити через `systemd`

## Отримання токена бота

1. Зайди на [discord.com/developers/applications](https://discord.com/developers/applications)
2. New Application → Bot → Reset Token → скопіюй токен
3. Увімкни інтенти: **Server Members Intent**, **Message Content Intent**
4. OAuth2 → URL Generator → scopes: `bot`, `applications.commands`
5. Дозволи: `Connect`, `Speak`, `Send Messages`, `Embed Links`
6. Запроси бота на сервер через згенерований URL

## Структура проекту

```
discord-music-bot/
├── bot.py                  # Основний файл бота
├── requirements.txt        # Залежності
├── discord-bot.service     # Systemd unit для автозапуску
└── SETUP.md                # Інструкція деплою на Proxmox
```
