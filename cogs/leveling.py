import discord
import time
import traceback
from discord.ext import commands, tasks
from discord import app_commands
from database import db
import asyncio
from settings import LEVELS, CHANNEL_ID, ITEMS_DB
from utils.generator import Generator, generate_image_in_thread
from utils.ui import RoadmapPagination, BattlepassView
from utils.logger import log

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_sessions = {} # {user_id: start_time}
        self.check_voice_xp.start()

    def cog_unload(self):
        self.check_voice_xp.cancel()

    # --- НОВЫЙ МЕТОД: СОХРАНЕНИЕ ПЕРЕД ВЫКЛЮЧЕНИЕМ ---
    async def save_all_sessions(self):
        """Сохраняет прогресс всех, кто сейчас в войсе, и очищает сессии"""
        if not self.voice_sessions:
            log("Нет активных голосовых сессий для сохранения.", level="INFO")
            return

        log(f"💾 Сохранение {len(self.voice_sessions)} активных сессий перед выключением...", level="WARN")
        
        now = time.time()
        tasks = []

        # Пробегаем по всем активным сессиям
        for user_id, start_time in list(self.voice_sessions.items()):
            duration = now - start_time
            xp_gained = int(duration / 60 * 10)
            if xp_gained > 0:
                # Находим объект участника (чтобы знать имя)
                guild = self.bot.get_guild(self.bot.guild_id) 
                member = guild.get_member(user_id) if guild else None
                
                # Добавляем задачу сохранения в список
                tasks.append(self.add_xp(member or user_id, xp_gained))
                log(f"💾 Сохранен прогресс: ID {user_id} (+{xp_gained} XP)", level="DEBUG")

        # Выполняем все сохранения параллельно
        if tasks:
            await asyncio.gather(*tasks)
        
        self.voice_sessions.clear()
        log("✅ Все сессии успешно сохранены.", level="SUCCESS")

    # --- НОВЫЙ МЕТОД: СКАНИРОВАНИЕ ПРИ ЗАПУСКЕ ---
    @commands.Cog.listener()
    async def on_ready(self):
        """Сканирует каналы при запуске и возобновляет сессии"""
        if self.scanned_on_startup: return
        
        log("🔄 Сканирование голосовых каналов...", level="INFO")
        count = 0
        now = time.time()

        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if member.bot: continue
                    
                    # Проверяем условия (мут/деф)
                    is_muted = member.self_mute or member.self_deaf or member.mute or member.deaf
                    
                    if not is_muted:
                        self.voice_sessions[member.id] = now
                        count += 1
        
        self.scanned_on_startup = True
        if count > 0:
            log(f"✅ Восстановлено сессий: {count}", level="SUCCESS")
        else:
            log("Никто не сидит в войсе.", level="INFO")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return

        is_muted = after.self_mute or after.self_deaf or after.mute or after.deaf
        
        # Вход в канал
        if before.channel is None and after.channel is not None:
            if not is_muted:
                self.voice_sessions[member.id] = time.time()
        
        # Выход из канала
        elif before.channel is not None and after.channel is None:
            await self.process_voice_session(member)
        
        # Переключение мута внутри канала
        elif before.channel is not None and after.channel is not None:
            was_muted = before.self_mute or before.self_deaf or before.mute or before.deaf
            
            # Включил мут (перестал фармить)
            if not was_muted and is_muted:
                await self.process_voice_session(member)
            # Выключил мут (начал фармить)
            elif was_muted and not is_muted:
                self.voice_sessions[member.id] = time.time()

    async def process_voice_session(self, member):
        if member.id in self.voice_sessions:
            start_time = self.voice_sessions.pop(member.id)
            duration = time.time() - start_time
            
            xp_gained = int(duration / 60 * 10)

            if xp_gained > 0:
                await self.add_xp(member, xp_gained)
                print(f"User {member.name} farmed {xp_gained} XP ({duration/60} mins)")

    @tasks.loop(minutes=5)
    async def check_voice_xp(self):
        # Начисляем опыт тем, кто сидит прямо сейчас, не дожидаясь выхода
        now = time.time()
        for user_id, start_time in list(self.voice_sessions.items()):
            duration = now - start_time
            xp_gained = int(duration / 60 * 10)
            if xp_gained > 0:
                member = self.bot.get_guild(self.bot.guild_id).get_member(user_id)
                if member:
                    await self.add_xp(member, xp_gained)
                    self.voice_sessions[user_id] = now # Сбрасываем таймер на "сейчас"

    async def add_xp(self, member, amount):
        user = await db.find_user(member.id)
        if not user:
            user = await db.create_user(member.id, member.name)
        
        current_xp = user['xp'] + amount
        current_lvl = user['level']
        
        # Проверка повышения уровня
        next_lvl_data = LEVELS.get(current_lvl + 1)
        if next_lvl_data and current_xp >= next_lvl_data['exp_need']:
            new_lvl = current_lvl + 1
            await db.update_user(member.id, {"xp": current_xp, "level": new_lvl})
            
            # Уведомление
            channel = self.bot.get_channel(CHANNEL_ID)
            if channel:
                await channel.send(f"🎉 {member.mention} достиг уровня {new_lvl}!")
        else:
            await db.update_user(member.id, {"xp": current_xp})

    @app_commands.command(name="roadmap", description="Карта наград и уровней")
    async def roadmap(self, interaction: discord.Interaction):
        # await interaction.response.defer(thinking=True)
        await interaction.response.defer(thinking=True)
        
        try:
            # --- ОТЛАДКА 1: Проверка базы данных ---
            log("Ищу пользователя в БД...", level="DEBUG")
            user = await db.find_user(interaction.user.id)
            
            if not user:
                log("Пользователь не найден в БД", level="WARN")
                return await interaction.followup.send("Ваш профиль не найден в базе. Обратитесь к <@namequalsmain>")
            
            log(f"Пользователь найден: {user.get('username')}", level="SUCCESS")

            # --- ОТЛАДКА 2: Проверка переменных ---
            raw_level = user.get('level')
            raw_xp = user.get('xp')
            
            log(f"Данные из БД -> Level: {raw_level} ({type(raw_level)}), XP: {raw_xp}", level='DEBUG')
            log(f"LEVELS загружен? Тип: {type(LEVELS)}", level='DEBUG')
            if isinstance(LEVELS, dict):
                log(f"Количество уровней в конфиге: {len(LEVELS)}", level='DEBUG')
            else:
                log("LEVELS ЭТО НЕ СЛОВАРЬ! Ошибка в settings.py", level='DEBUG')

            # --- ИСПРАВЛЕНИЕ ВОЗМОЖНЫХ ОШИБОК ---
            # 1. Если уровня нет или он None -> ставим 1
            if raw_level is None:
                lvl = 1
            else:
                lvl = int(raw_level) # Принудительно превращаем в число
            
            # 2. Если XP нет -> ставим 0
            current_xp = int(raw_xp) if raw_xp is not None else 0

            # Логика страниц
            if lvl == 0: lvl = 1
            page = 1
            if lvl > 10: page = 2
            if lvl > 20: page = 3

            # --- ВОТ ТА САМАЯ "ПРОБЛЕМНАЯ" СТРОКА ---
            log(f"Calculated LVL: {lvl}. Trying to get next level info...", level='DEBUG')
            
            # Безопасное получение следующего уровня
            next_lvl_key = lvl + 1
            
            # Проверяем, существует ли ключ в словаре
            if next_lvl_key in LEVELS:
                need_xp = LEVELS[next_lvl_key]['exp_need']
            else:
                log(f"Уровня {next_lvl_key} нет в конфиге. Ставлю заглушку.", level="WARN")
                need_xp = current_xp # Или любое число

            log(f"Цель XP: {need_xp}", level='DEBUG')

            # --- ГЕНЕРАЦИЯ ---
            log("Запускаю генератор...", level="DEBUG")
            buffer = await generate_image_in_thread(
                Generator.create_roadmap,
                interaction.user.name,
                interaction.user.display_avatar.url,
                current_xp,
                need_xp,
                lvl,
                page,
                LEVELS
            )
            
            if buffer is None:
                await interaction.followup.send("Ошибка генерации (см. консоль)")
                return

            file = discord.File(fp=buffer, filename="roadmap.png")
            view = RoadmapPagination(interaction.user, page, user)
            await interaction.followup.send(file=file, view=view, ephemeral=True)
            log("Сообщение отправлено!", level="SUCCESS")

        except Exception as e:
            # ЭТО ПОКАЖЕТ ТЕБЕ ОШИБКУ В ТЕРМИНАЛЕ
            log(f"КРИТИЧЕСКАЯ ОШИБКА В КОМАНДЕ ROADMAP:\n{e}", level='ERROR')
            print(traceback.format_exc())
            await interaction.followup.send(f"Произошла ошибка: {e}")
    @app_commands.command(name="battlepass", description="Посмотреть прогресс и уровень")
    async def battlepass(self, interaction: discord.Interaction):
        
        try:
            await interaction.response.defer(thinking=True, ephemeral=True) 

            log("Ищу пользователя в БД...", level="DEBUG")
            user = await db.find_user(interaction.user.id)
            
            if not user:
                log("Пользователь не найден в БД, добавляю", level="WARN")
                await db.create_user(interaction.user.id, interaction.user.display_name)
            
            log(f"Пользователь найден: {user.get('username')}", level="SUCCESS")
            lvl = user['level']
            xp = user['xp']
            next_lvl_key = lvl + 1
            if next_lvl_key in LEVELS:
                need_xp = LEVELS[next_lvl_key]['exp_need']
            else:
                log(f"Уровня {next_lvl_key} нет в конфиге. Ставлю заглушку.", level="WARN")
                need_xp = user['xp'] # Или любое число
            buffer = await generate_image_in_thread(
                Generator.create_bp_card,
                interaction.user.name,
                lvl,
                xp,
                need_xp,
                interaction.user.display_avatar.url,
            )
            view = BattlepassView(interaction.user.id)

            file = discord.File(fp=buffer, filename="roadmap.png")
            await interaction.followup.send(file=file, view=view)
        except Exception as e:
            # ЭТО ПОКАЖЕТ ТЕБЕ ОШИБКУ В ТЕРМИНАЛЕ
            log(f"КРИТИЧЕСКАЯ ОШИБКА В КОМАНДЕ BATTLEPASS:\n{e}", level='ERROR')
            print(traceback.format_exc())
            await interaction.followup.send(f"Произошла ошибка: {e}")
    @app_commands.command(name="profile", description="Посмотреть профиль")
    async def profile_slash(self, interaction: discord.Interaction):
        user = interaction.user
            
        await interaction.response.defer(thinking=True)
        
        db_user = await db.find_user(user.id)
        if not db_user:
             return await interaction.followup.send(f"❌ У пользователя {user.name} нет профиля.")

        lvl = db_user.get('level', 0)
        xp = db_user.get('xp', 0)
        
        # Дата регистрации (из БД)
        reg_ts = db_user.get('reg_date', 0)
        # Форматируем дату для Дискорда: <t:TIMESTAMP:D> (например: "15 мая 2024")
        reg_date_str = f"<t:{int(reg_ts)}:D>" if reg_ts else "Неизвестно"

        # Инвентарь (топ 5 предметов)
        inv = db_user.get('inventory', {})
        items_list = []
        for i_id, count in inv.items():
            if count > 0:
                data = ITEMS_DB.get(i_id, {})
                emoji = data.get('emoji', '📦')
                items_list.append(f"{emoji} x{count}")
        
        inv_str = " | ".join(items_list[:5])
        if len(items_list) > 5: inv_str += f" и еще {len(items_list)-5}..."
        if not inv_str: inv_str = "Пусто"

        # Следующий уровень
        next_lvl_xp = LEVELS.get(lvl + 1, {}).get('exp_need', xp)
        progress_percent = int((xp / next_lvl_xp) * 100) if next_lvl_xp > 0 else 100
        
        # Генерация Embed
        embed = discord.Embed(title=f"Профиль {user.display_name}", color=user.color)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        embed.add_field(name="⭐ Уровень", value=f"**{lvl}**", inline=True)
        embed.add_field(name="📊 Опыт", value=f"`{xp} / {next_lvl_xp}` ({progress_percent}%)", inline=True)
        embed.add_field(name="📅 Дата начала", value=reg_date_str, inline=True)
        
        embed.add_field(name="🎒 Инвентарь (Топ)", value=inv_str, inline=False)
        
        # Кнопка для просмотра полного инвентаря
        from utils.ui import BattlepassView # Импортируем только View для кнопки
        view = BattlepassView(user.id) 
            # (BattlepassView содержит кнопку "Рюкзак")

        await interaction.followup.send(embed=embed, view=view)

async def setup(bot):
    # Костыль для получения ID гильдии внутри таска, лучше передать в init
    bot.guild_id = 1173882167504408626 
    await bot.add_cog(Leveling(bot))