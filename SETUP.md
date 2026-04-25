# Налаштування Discord Music Bot на Proxmox LXC

## 1. Створити LXC контейнер на Proxmox

В веб-інтерфейсі Proxmox:
- Create CT → Ubuntu 22.04
- RAM: 512 MB (достатньо)
- Disk: 4 GB
- CPU: 1 core
- Увімкнути: Start at boot

## 2. Зайти в контейнер і встановити залежності

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv ffmpeg git
```

## 3. Створити користувача

```bash
useradd -m -s /bin/bash botuser
```

## 4. Скопіювати файли боту

З Windows (в PowerShell/термінал):
```
scp -r C:\Users\38099\discord-music-bot root@<IP_PROXMOX_CT>:/opt/
```

Або напряму на контейнері через git:
```bash
mkdir /opt/discord-music-bot
# скопіюй файли вручну або через scp
```

## 5. Налаштувати virtualenv

```bash
cd /opt/discord-music-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 6. Отримати токен Discord бота

1. Зайди на https://discord.com/developers/applications
2. New Application → дай назву
3. Bot → Add Bot → Reset Token → скопіюй токен
4. Під "Privileged Gateway Intents" увімкни: Server Members Intent, Message Content Intent
5. OAuth2 → URL Generator → scopes: bot, applications.commands
6. Bot Permissions: Connect, Speak, Send Messages, Embed Links
7. Скопіюй URL і запроси бота на сервер

## 7. Налаштувати systemd service

```bash
cp /opt/discord-music-bot/discord-bot.service /etc/systemd/system/
# Відредагуй токен:
nano /etc/systemd/system/discord-bot.service
# Встав свій токен замість "ВАШ_ТОКЕН_ТУТ"

systemctl daemon-reload
systemctl enable discord-bot
systemctl start discord-bot
systemctl status discord-bot
```

## 8. Перевірити логи

```bash
journalctl -u discord-bot -f
```

---

## Команди бота (слеш-команди)

| Команда | Опис |
|---|---|
| `/play <назва або URL>` | Грати трек або додати до черги |
| `/queue` | Показати чергу |
| `/skip` | Пропустити поточний трек |
| `/stop` | Зупинити і відключитись |
| `/pause` | Пауза |
| `/resume` | Продовжити |
| `/shuffle` | Перемішати чергу |
| `/clear` | Очистити чергу |
| `/nowplaying` | Поточний трек |
| `/volume <0-100>` | Гучність |
| `/remove <номер>` | Видалити трек з черги |

Підтримує:
- YouTube посилання на окремий відео
- YouTube плейлисти (додає всі треки)
- Пошук по назві (наприклад `/play lofi hip hop`)
