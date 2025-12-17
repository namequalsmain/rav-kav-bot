import discord
import traceback
from discord import app_commands, ui
import asyncio
from discord.ext import commands
from database import db
from settings import ITEMS_DB, LEVELS
from utils.logger import log

# --- 1. ВЫПАДАЮЩИЙ СПИСОК УРОВНЕЙ ---
class LevelSelect(ui.Select):
    def __init__(self, target_user):
        self.target_user = target_user
        
        # Генерируем опции на основе levels.json
        options = []
        
        # Сортируем уровни по возрастанию
        sorted_levels = sorted(LEVELS.items())
        
        # Дискорд разрешает максимум 25 опций. Берем первые 25.
        # Если уровней больше, нужно делать пагинацию (но пока хватит 25)
        for i, (lvl_num, data) in enumerate(sorted_levels[:25]):
            
            min_xp = data['exp_need']
            
            # Вычисляем макс. XP (это XP следующего уровня - 1)
            # Если следующего уровня нет, пишем "и выше"
            if i + 1 < len(sorted_levels):
                next_xp = sorted_levels[i+1][1]['exp_need']
                range_str = f"{min_xp} - {next_xp - 1} XP"
            else:
                range_str = f"{min_xp}+ XP"

            options.append(discord.SelectOption(
                label=f"Уровень {lvl_num}",
                value=str(lvl_num), # Значение должно быть строкой
                description=f"Диапазон: {range_str}",
                emoji="⭐"
            ))

        super().__init__(placeholder="Выберите уровень для установки...", options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_lvl = int(self.values[0])
            required_xp = LEVELS[selected_lvl]['exp_need']
            
            # Обновляем в БД
            await db.update_user(self.target_user.id, {
                "level": selected_lvl,
                "xp": required_xp # Сразу ставим минимальный порог XP
            })
            
            log(f"Админ {interaction.user} установил юзеру {self.target_user} уровень {selected_lvl}", level="SUCCESS")
            
            await interaction.response.send_message(
                f"✅ Пользователю {self.target_user.mention} установлен **Уровень {selected_lvl}** (XP сброшен до {required_xp}).", 
                ephemeral=True
            )
        except Exception as e:
            log(f"Ошибка выбора уровня: {e}", level="ERROR")
            await interaction.response.send_message("Ошибка при установке уровня.", ephemeral=True)

# View, которая держит этот список
class LevelSelectView(ui.View):
    def __init__(self, target_user):
        super().__init__(timeout=60)
        self.add_item(LevelSelect(target_user))


# --- 2. МОДАЛЬНОЕ ОКНО ТОЛЬКО ДЛЯ XP (РУЧНОЕ) ---
class ManualXPModal(ui.Modal, title="Изменить XP"):
    def __init__(self, target_user):
        super().__init__()
        self.target_user = target_user

    xp_amount = ui.TextInput(
        label="Изменить XP (+ добавить, - отнять)",
        placeholder="Например: 500 или -100",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.xp_amount.value)
            user_data = await db.find_user(self.target_user.id)
            
            if not user_data: # Если юзера нет, создаем
                await db.create_user(self.target_user.id, self.target_user.name)
                user_data = {"xp": 0}

            current_xp = user_data.get('xp', 0)
            new_xp = max(0, current_xp + amount)
            exp_need = LEVELS[user_data['level']]['exp_need'] if (user_data['level'] + 1) in LEVELS else None
            if new_xp >= exp_need and exp_need is not None:
                for lvl in range(user_data['level'], len(LEVELS)):
                    lvl_data = LEVELS[lvl]
                    if lvl_data['exp_need'] <= new_xp and lvl != 30:
                        continue
                    else:
                        await db.update_user(self.target_user.id, {"level": lvl})
                        break
         
            # exp_need = LEVELS[next_lvl]['exp_need'] if (next_lvl) in LEVELS else None
            await db.update_user(self.target_user.id, {"xp": new_xp})
            # if new_xp >= exp_need and exp_need is not None:
            #     await db.update_user(self.target_user.id, {"level": next_lvl})
            
            log(f"Админ {interaction.user} изменил XP {self.target_user}: {current_xp} -> {new_xp}", level="DEBUG")
            await interaction.response.send_message(f"✅ XP изменен: **{current_xp}** ➡️ **{new_xp}**", ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("❌ Введите число!", ephemeral=True)
        except Exception as e:
            log(f"Ошибка Modal XP: {e}", level="ERROR")


# --- 3. МОДАЛКА ДЛЯ ПРЕДМЕТОВ (Оставляем как было) ---
class ItemAmountModal(ui.Modal, title="Выдача предмета"):
    def __init__(self, target_user, item_id, item_name):
        super().__init__()
        self.target_user = target_user
        self.item_id = item_id
        self.title = f"Выдать: {item_name}"

    amount = ui.TextInput(label="Количество", default="1", placeholder="1")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.amount.value)
            await db.add_item(self.target_user.id, self.item_id, count)
            action = "Выдано" if count > 0 else "Забрано"
            await interaction.response.send_message(f"✅ {action} {count} шт. `{self.item_id}`", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Введите число!", ephemeral=True)


# --- 4. ГЛАВНАЯ ПАНЕЛЬ ---
class AdminPanelView(ui.View):
    def __init__(self, target_user):
        super().__init__(timeout=180)
        self.target_user = target_user
        self.setup_item_select()

    def setup_item_select(self):
        if not ITEMS_DB: return
        options = []
        for item_id, data in ITEMS_DB.items():
            options.append(discord.SelectOption(
                label=data.get('name', item_id), value=item_id, emoji=data.get('emoji', '❓')
            ))
        select = ui.Select(placeholder="🎒 Выдать предмет...", options=options[:25])
        select.callback = self.item_select_callback
        self.add_item(select)

    async def item_select_callback(self, interaction: discord.Interaction):
        selected = interaction.data['values'][0]
        await interaction.response.send_modal(ItemAmountModal(self.target_user, selected, ITEMS_DB[selected]['name']))

    # КНОПКА 1: Выбрать уровень из списка
    @ui.button(label="Установить Уровень", style=discord.ButtonStyle.success, emoji="🏆")
    async def set_level_btn(self, interaction: discord.Interaction, button: ui.Button):
        # Отправляем новое сообщение с выпадающим списком уровней
        await interaction.response.send_message(
            "Выберите уровень из списка ниже:", 
            view=LevelSelectView(self.target_user), 
            ephemeral=True
        )

    # КНОПКА 2: Ручное XP
    @ui.button(label="Выдать EXP", style=discord.ButtonStyle.primary, emoji="📊")
    async def edit_xp_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ManualXPModal(self.target_user))

    @ui.button(label="Обновить конфиги", style=discord.ButtonStyle.secondary, emoji="⚙️")
    async def reload_config_btn(self, interaction: discord.Interaction, button: ui.Button):
        try:
            import settings
            
            # 1. Загружаем свежие данные из файлов в ВРЕМЕННЫЕ переменные
            new_levels = settings.load_json_file('levels.json', key_is_int=True)
            new_items = settings.load_json_file('items_data.json', key_is_int=False)
            
            # 2. ВАЖНО: Не используем знак "=", а меняем содержимое существующих словарей!
            # Это позволяет другим файлам (inventory.py, leveling.py) увидеть изменения без перезагрузки
            
            # Обновляем Уровни
            settings.LEVELS.clear()          # Удаляем старое
            settings.LEVELS.update(new_levels) # Заливаем новое
            
            # Обновляем Предметы
            settings.ITEMS_DB.clear()
            settings.ITEMS_DB.update(new_items)
            
            from utils.logger import log
            log(f"Конфиги обновлены (Hot Reload). Levels: {len(settings.LEVELS)}, Items: {len(settings.ITEMS_DB)}", level="SUCCESS")
            
            await interaction.response.send_message(
                f"✅ Конфиги обновлены!\nItems: {len(settings.ITEMS_DB)}\nLevels: {len(settings.LEVELS)}", 
                ephemeral=True
            )
            
        except Exception as e:
            from utils.logger import log
            log(f"Ошибка перезагрузки конфига: {e}", level="ERROR")
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)


# --- 5. КОГ ADMIN ---
class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="admin", description="Панель управления пользователем")
    @app_commands.describe(user="Пользователь")
    @app_commands.default_permissions(administrator=True) 
    async def admin_panel(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
             return await interaction.response.send_message("⛔ Только для админов!", ephemeral=True)

        db_user = await db.find_user(user.id)
        embed = discord.Embed(title="🛠️ Админ Панель", color=discord.Color.dark_red())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=user.mention, inline=False)
        
        if db_user:
            lvl = db_user.get('level', 0)
            xp = db_user.get('xp', 0)
            inv = db_user.get('inventory', {})
            inv_str = ", ".join([f"{k}: {v}" for k,v in inv.items() if v > 0]) or "Пусто"
            
            # Показываем инфу о следующем уровне
            if (lvl + 1) in LEVELS:
                next_xp = LEVELS[lvl+1]['exp_need']
                embed.add_field(name="Прогресс", value=f"XP: `{xp} / {next_xp}`", inline=True)
            else:
                embed.add_field(name="Прогресс", value=f"XP: `{xp}` (Макс)", inline=True)

            embed.add_field(name="Уровень", value=f"⭐ **{lvl}**", inline=True)
            embed.add_field(name="Инвентарь", value=inv_str, inline=False)
        else:
            embed.add_field(name="Status", value="⚠️ Нет в БД (Будет создан при действии)", inline=False)

        await interaction.response.send_message(embed=embed, view=AdminPanelView(user), ephemeral=True)


    @commands.command(name="sync")
    @commands.has_permissions(administrator=True)
    async def sync_tree(self, ctx):
        await ctx.send("⏳ Синхронизация...")
        try:
            self.bot.tree.copy_global_to(guild=ctx.guild)
            await self.bot.tree.sync(guild=ctx.guild)
            await ctx.send("✅ Готово!")
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {e}")


    @commands.command(name="sync_db")
    @commands.has_permissions(administrator=True)
    async def sync_db(self, ctx):
        """Синхронизация базы данных, добавляет всех пользователей на сервере в бд"""
        members = ctx.guild.members
        await asyncio.gather(*[db.create_user(user_id=member.id, username=member.name) for member in members])
        await ctx.send(f"✅ База данных успешно синхронизирована")


    @commands.command(name="global_sync")
    @commands.has_permissions(administrator=True)
    async def fast_sync(self,ctx):
        self.bot.tree.copy_global_to(guild=ctx.guild) # Копируем глобальные команды в этот сервер
        await self.bot.tree.sync(guild=ctx.guild)
        await ctx.send("⚡ Команды синхронизированы мгновенно для этого сервера!")


    @commands.command(name="clear_duplicates")
    @commands.has_permissions(administrator=True)
    async def clear_duplicates(self,ctx):
        # Эта команда очистит список команд конкретно для ЭТОГО сервера
        self.bot.tree.clear_commands(guild=ctx.guild)
        await self.bot.tree.sync(guild=ctx.guild)
        await ctx.send("Локальные команды сервера удалены. Теперь должны остаться только глобальные.")

async def setup(bot):
    await bot.add_cog(Admin(bot))