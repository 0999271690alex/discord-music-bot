import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import random
from collections import deque
import os

TOKEN = os.getenv("DISCORD_TOKEN")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


class Track:
    def __init__(self, data: dict):
        self.title: str = data.get("title", "Unknown")
        self.url: str = data.get("webpage_url", "")
        self.stream_url: str = data.get("url", "")
        self.duration: int = data.get("duration", 0)
        self.thumbnail: str = data.get("thumbnail", "")

    def create_source(self) -> discord.PCMVolumeTransformer:
        return discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(self.stream_url, **FFMPEG_OPTIONS),
            volume=0.5,
        )

    def format_duration(self) -> str:
        if not self.duration:
            return "?"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class MusicPlayer:
    def __init__(self):
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.channel: discord.TextChannel | None = None
        self.voice_client: discord.VoiceClient | None = None
        self._next = asyncio.Event()

    def add(self, track: Track) -> None:
        self.queue.append(track)

    def add_many(self, tracks: list[Track]) -> None:
        self.queue.extend(tracks)

    def shuffle(self) -> None:
        lst = list(self.queue)
        random.shuffle(lst)
        self.queue = deque(lst)

    def clear(self) -> None:
        self.queue.clear()

    async def player_loop(self) -> None:
        while True:
            self._next.clear()
            if not self.queue:
                self.current = None
                await asyncio.sleep(1)
                continue

            self.current = self.queue.popleft()

            try:
                source = self.current.create_source()
            except Exception as e:
                if self.channel:
                    await self.channel.send(f"Помилка завантаження треку: {e}")
                continue

            self.voice_client.play(source, after=lambda _: self._next.set())

            if self.channel:
                await self.channel.send(embed=build_now_playing(self.current))

            await self._next.wait()

            if not self.voice_client or not self.voice_client.is_connected():
                break


players: dict[int, MusicPlayer] = {}
player_tasks: dict[int, asyncio.Task] = {}


def get_player(guild: discord.Guild) -> MusicPlayer:
    gid = guild.id
    if gid not in players:
        players[gid] = MusicPlayer()
    return players[gid]


def build_now_playing(track: Track) -> discord.Embed:
    embed = discord.Embed(
        title="Зараз грає",
        description=f"[{track.title}]({track.url})",
        color=0x1DB954,
    )
    embed.add_field(name="Тривалість", value=track.format_duration())
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    return embed


async def fetch_tracks(query: str) -> list[Track]:
    loop = asyncio.get_event_loop()

    def extract():
        if query.startswith("http"):
            return ytdl.extract_info(query, download=False)
        return ytdl.extract_info(f"ytsearch:{query}", download=False)

    data = await loop.run_in_executor(None, extract)
    if not data:
        return []

    if "entries" in data:
        return [Track(e) for e in data["entries"] if e and e.get("url")]
    return [Track(data)] if data.get("url") else []


async def ensure_voice(interaction: discord.Interaction) -> bool:
    if not interaction.user.voice:
        await interaction.followup.send("Зайди в голосовий канал!")
        return False

    channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client

    if not vc:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)

    player = get_player(interaction.guild)
    player.voice_client = vc
    player.channel = interaction.channel
    return True


async def start_player_loop(guild: discord.Guild) -> None:
    gid = guild.id
    if gid in player_tasks and not player_tasks[gid].done():
        return
    player = get_player(guild)
    player_tasks[gid] = asyncio.create_task(player.player_loop())


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} slash commands")


@bot.tree.command(name="play", description="Грати трек або додати до черги")
@app_commands.describe(query="YouTube URL, посилання на плейлист або назва треку")
async def play_cmd(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    if not await ensure_voice(interaction):
        return

    tracks = await fetch_tracks(query)
    if not tracks:
        await interaction.followup.send("Нічого не знайдено.")
        return

    player = get_player(interaction.guild)
    player.add_many(tracks)

    if len(tracks) == 1:
        if player.current is not None:
            embed = discord.Embed(
                title="Додано до черги",
                description=f"[{tracks[0].title}]({tracks[0].url})",
                color=0x0099FF,
            )
            embed.add_field(name="Тривалість", value=tracks[0].format_duration())
            embed.add_field(name="Позиція", value=str(len(player.queue)))
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("Починаю відтворення...")
    else:
        await interaction.followup.send(f"Додано **{len(tracks)}** треків до черги!")

    await start_player_loop(interaction.guild)


@bot.tree.command(name="skip", description="Пропустити поточний трек")
async def skip_cmd(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        await interaction.response.send_message("Нічого не грає.")
        return
    vc.stop()
    await interaction.response.send_message("Пропущено!")


@bot.tree.command(name="stop", description="Зупинити відтворення і відключитись")
async def stop_cmd(interaction: discord.Interaction):
    gid = interaction.guild_id
    player = get_player(interaction.guild)
    player.clear()
    player.current = None

    if gid in player_tasks:
        player_tasks[gid].cancel()
        del player_tasks[gid]

    players.pop(gid, None)

    vc = interaction.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()

    await interaction.response.send_message("Зупинено.")


@bot.tree.command(name="queue", description="Показати чергу треків")
async def queue_cmd(interaction: discord.Interaction):
    player = get_player(interaction.guild)

    if not player.current and not player.queue:
        await interaction.response.send_message("Черга порожня.")
        return

    embed = discord.Embed(title="Черга", color=0x0099FF)

    if player.current:
        embed.add_field(
            name="Зараз грає",
            value=f"[{player.current.title}]({player.current.url}) `{player.current.format_duration()}`",
            inline=False,
        )

    if player.queue:
        items = list(player.queue)[:15]
        lines = [
            f"`{i + 1}.` [{t.title}]({t.url}) `{t.format_duration()}`"
            for i, t in enumerate(items)
        ]
        if len(player.queue) > 15:
            lines.append(f"... і ще {len(player.queue) - 15} треків")
        embed.add_field(
            name=f"Черга ({len(player.queue)} треків)",
            value="\n".join(lines),
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="shuffle", description="Перемішати чергу")
async def shuffle_cmd(interaction: discord.Interaction):
    player = get_player(interaction.guild)
    if not player.queue:
        await interaction.response.send_message("Черга порожня.")
        return
    player.shuffle()
    await interaction.response.send_message(f"Перемішано {len(player.queue)} треків!")


@bot.tree.command(name="clear", description="Очистити чергу")
async def clear_cmd(interaction: discord.Interaction):
    player = get_player(interaction.guild)
    player.clear()
    await interaction.response.send_message("Чергу очищено.")


@bot.tree.command(name="pause", description="Поставити на паузу")
async def pause_cmd(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("Пауза.")
    else:
        await interaction.response.send_message("Нічого не грає.")


@bot.tree.command(name="resume", description="Продовжити відтворення")
async def resume_cmd(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("Продовжено.")
    else:
        await interaction.response.send_message("Нічого не на паузі.")


@bot.tree.command(name="nowplaying", description="Показати поточний трек")
async def nowplaying_cmd(interaction: discord.Interaction):
    player = get_player(interaction.guild)
    if not player.current:
        await interaction.response.send_message("Нічого не грає.")
        return
    await interaction.response.send_message(embed=build_now_playing(player.current))


@bot.tree.command(name="volume", description="Змінити гучність (0–100)")
@app_commands.describe(level="Рівень гучності від 0 до 100")
async def volume_cmd(interaction: discord.Interaction, level: int):
    if not 0 <= level <= 100:
        await interaction.response.send_message("Вкажи число від 0 до 100.")
        return
    vc = interaction.guild.voice_client
    if vc and vc.source:
        vc.source.volume = level / 100
        await interaction.response.send_message(f"Гучність: **{level}%**")
    else:
        await interaction.response.send_message("Нічого не грає.")


@bot.tree.command(name="remove", description="Видалити трек з черги за номером")
@app_commands.describe(position="Номер треку в черзі")
async def remove_cmd(interaction: discord.Interaction, position: int):
    player = get_player(interaction.guild)
    if not player.queue or position < 1 or position > len(player.queue):
        await interaction.response.send_message("Невірний номер.")
        return
    lst = list(player.queue)
    removed = lst.pop(position - 1)
    player.queue = deque(lst)
    await interaction.response.send_message(f"Видалено: **{removed.title}**")


bot.run(TOKEN)
