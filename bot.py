import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import random
import time
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
YTDL_FLAT_OPTIONS = {**YTDL_OPTIONS, "extract_flat": "in_playlist"}
ytdl_flat = yt_dlp.YoutubeDL(YTDL_FLAT_OPTIONS)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

QUEUE_PAGE_SIZE = 10
BAR_LENGTH = 18


def format_seconds(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_progress_bar(elapsed: int, total: int) -> str:
    ratio = min(elapsed / total, 1.0) if total else 0
    pos = int(BAR_LENGTH * ratio)
    bar = "▬" * pos + "🔘" + "▬" * (BAR_LENGTH - pos)
    return f"{bar}\n`{format_seconds(elapsed)} / {format_seconds(total)}`"


class Track:
    def __init__(self, data: dict):
        self.title: str = data.get("title", "Unknown")
        self.url: str = data.get("webpage_url", data.get("url", ""))
        self.stream_url: str = data.get("url", "") if "webpage_url" in data else ""
        self.duration: int = data.get("duration", 0)
        self.thumbnail: str = data.get("thumbnail", "")
        if not self.url and data.get("id"):
            self.url = f"https://www.youtube.com/watch?v={data['id']}"

    async def resolve_stream_url(self) -> bool:
        if self.stream_url:
            return True
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(self.url, download=False)
        )
        if not data or not data.get("url"):
            return False
        self.stream_url = data["url"]
        if not self.thumbnail:
            self.thumbnail = data.get("thumbnail", "")
        if not self.duration:
            self.duration = data.get("duration", 0)
        return True

    def create_source(self) -> discord.PCMVolumeTransformer:
        return discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(self.stream_url, **FFMPEG_OPTIONS),
            volume=0.5,
        )

    def format_duration(self) -> str:
        if not self.duration:
            return "?"
        return format_seconds(self.duration)


class MusicPlayer:
    def __init__(self):
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.channel: discord.TextChannel | None = None
        self.voice_client: discord.VoiceClient | None = None
        self._next = asyncio.Event()
        self._started_at: float = 0.0

    def elapsed(self) -> int:
        if not self._started_at:
            return 0
        return int(time.monotonic() - self._started_at)

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
        idle_since: float | None = None
        while True:
            self._next.clear()
            if not self.queue:
                self.current = None
                self._started_at = 0.0
                if idle_since is None:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since >= 300:
                    if self.voice_client and self.voice_client.is_connected():
                        if self.channel:
                            await self.channel.send("Черга порожня — відключаюсь.")
                        await self.voice_client.disconnect()
                    break
                await asyncio.sleep(5)
                continue
            idle_since = None

            self.current = self.queue.popleft()

            try:
                if not await self.current.resolve_stream_url():
                    if self.channel:
                        await self.channel.send(f"Не вдалося отримати трек: {self.current.title}")
                    continue
                source = self.current.create_source()
            except Exception as e:
                if self.channel:
                    await self.channel.send(f"Помилка завантаження треку: {e}")
                continue

            self._started_at = time.monotonic()
            self.voice_client.play(source, after=lambda _: self._next.set())

            if self.channel:
                await self.channel.send(
                    embed=build_now_playing(self.current, 0),
                    view=NowPlayingView(),
                )

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


def build_now_playing(track: Track, elapsed: int = -1) -> discord.Embed:
    embed = discord.Embed(
        title="Зараз грає",
        description=f"[{track.title}]({track.url})",
        color=0x1DB954,
    )
    if track.duration and elapsed >= 0:
        embed.add_field(name="Прогрес", value=build_progress_bar(elapsed, track.duration), inline=False)
    else:
        embed.add_field(name="Тривалість", value=track.format_duration(), inline=False)
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    return embed


class NowPlayingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji="⏸", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("Бот не в каналі.", ephemeral=True)
            return
        if vc.is_playing():
            vc.pause()
            button.emoji = "▶️"
        elif vc.is_paused():
            vc.resume()
            button.emoji = "⏸"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("Пропущено!", ephemeral=True)
        else:
            await interaction.response.send_message("Нічого не грає.", ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = get_player(interaction.guild)
        if not player.queue:
            await interaction.response.send_message("Черга порожня.", ephemeral=True)
            return
        player.shuffle()
        await interaction.response.send_message(
            f"Перемішано {len(player.queue)} треків!", ephemeral=True
        )


class QueueView(discord.ui.View):
    def __init__(self, player: MusicPlayer, page: int = 0):
        super().__init__(timeout=120)
        self.player = player
        self.page = page
        self._refresh_buttons()

    def _total_pages(self) -> int:
        return max(1, (len(self.player.queue) + QUEUE_PAGE_SIZE - 1) // QUEUE_PAGE_SIZE)

    def _refresh_buttons(self) -> None:
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self._total_pages() - 1

    def build_embed(self) -> discord.Embed:
        items = list(self.player.queue)
        total_pages = self._total_pages()
        start = self.page * QUEUE_PAGE_SIZE
        page_items = items[start:start + QUEUE_PAGE_SIZE]
        embed = discord.Embed(
            title=f"Черга — сторінка {self.page + 1}/{total_pages}",
            color=0x0099FF,
        )
        if self.player.current:
            embed.add_field(
                name="Зараз грає",
                value=f"[{self.player.current.title}]({self.player.current.url}) `{self.player.current.format_duration()}`",
                inline=False,
            )
        if page_items:
            lines = [
                f"`{start + i + 1}.` [{t.title}]({t.url}) `{t.format_duration()}`"
                for i, t in enumerate(page_items)
            ]
            embed.add_field(
                name=f"Черга ({len(items)} треків)",
                value="\n".join(lines),
                inline=False,
            )
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self._total_pages() - 1, self.page + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


async def fetch_tracks(query: str) -> list[Track]:
    loop = asyncio.get_event_loop()

    def extract():
        if query.startswith("http"):
            data = ytdl_flat.extract_info(query, download=False)
            if data and "entries" in data:
                return data
            return ytdl.extract_info(query, download=False)
        return ytdl.extract_info(f"ytsearch:{query}", download=False)

    data = await loop.run_in_executor(None, extract)
    if not data:
        return []

    if "entries" in data:
        return [
            Track(e) for e in data["entries"]
            if e and (e.get("url") or e.get("webpage_url") or e.get("id"))
        ]
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
    if not vc or not (vc.is_playing() or vc.is_paused()):
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
    view = QueueView(player)
    await interaction.response.send_message(embed=view.build_embed(), view=view)


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
    await interaction.response.send_message(
        embed=build_now_playing(player.current, player.elapsed()),
        view=NowPlayingView(),
    )


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
