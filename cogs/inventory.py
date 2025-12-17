import discord
import random
import asyncio
from discord import app_commands, ui
from discord.ext import commands
from database import db
from settings import ITEMS_DB

# --- 1. МЕНЮ ВЫБОРА ПОЛЬЗОВАТЕЛЯ (User Select) ---
class TargetSelect(ui.UserSelect):
    def __init__(self, item_id, item_name):
        super().__init__(
            placeholder=f"Выберите цель для {item_name}...",
            min_values=1,
            max_values=1
        )
        self.item_id = item_id

    async def callback(self, interaction: discord.Interaction):
        # Получаем выбранного пользователя (это объект Member)
        target = self.values[0]
        
        # Передаем управление логике
        await InventoryLogic.process_use(interaction, self.item_id, target)

class TargetSelectView(ui.View):
    def __init__(self, item_id, item_name):
        super().__init__(timeout=60)
        self.add_item(TargetSelect(item_id, item_name))

# --- 2. МЕНЮ ПОДТВЕРЖДЕНИЯ (Для предметов БЕЗ цели) ---
class ConfirmView(ui.View):
    def __init__(self, item_id, item_name):
        super().__init__(timeout=60)
        self.item_id = item_id
        self.item_name = item_name

    @ui.button(label="Активировать", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await InventoryLogic.process_use(interaction, self.item_id, None)

    @ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="❌ Отменено.", view=None)


# --- 3. КНОПКА ПРЕДМЕТА (В ГЛАВНОМ МЕНЮ) ---
class InventoryItemButton(ui.Button):
    def __init__(self, item_id, amount, item_data):
        self.item_id = item_id
        label = f"{item_data.get('name', item_id)} (x{amount})"
        emoji = item_data.get('emoji', '📦')
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        # Определяем, нужен ли таргет
        needs_target = self.item_id in ['kick', 'mute', 'rename', 'steal_xp', 'hook']
        item_name = ITEMS_DB.get(self.item_id, {}).get('name', self.item_id)

        if needs_target:
            # Если нужен таргет — отправляем меню выбора людей
            view = TargetSelectView(self.item_id, item_name)
            await interaction.response.send_message(
                f"🎯 Выберите, на ком использовать **{item_name}**:", 
                view=view, 
                ephemeral=True
            )
        else:
            # Если таргет не нужен — отправляем кнопку подтверждения
            view = ConfirmView(self.item_id, item_name)
            await interaction.response.send_message(
                f"❓ Вы уверены, что хотите использовать **{item_name}**?", 
                view=view, 
                ephemeral=True
            )


# --- 4. ПАГИНАЦИЯ ИНВЕНТАРЯ ---
class InventoryPaginationView(ui.View):
    def __init__(self, interaction, inventory_dict):
        super().__init__(timeout=180)
        self.interaction = interaction
        self.user_id = interaction.user.id
        self.items = list(inventory_dict.items())
        self.page = 0
        self.items_per_page = 20 
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        start = self.page * self.items_per_page
        end = start + self.items_per_page
        current_items = self.items[start:end]

        for item_id, amount in current_items:
            item_data = ITEMS_DB.get(item_id, {})
            self.add_item(InventoryItemButton(item_id, amount, item_data))

        if len(self.items) > self.items_per_page:
            total_pages = (len(self.items) - 1) // self.items_per_page + 1
            
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=4)
            prev_btn.callback = self.prev_callback
            self.add_item(prev_btn)

            counter_btn = ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.gray, disabled=True, row=4)
            self.add_item(counter_btn)

            next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(end >= len(self.items)), row=4)
            next_btn.callback = self.next_callback
            self.add_item(next_btn)

    async def prev_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def next_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)


# --- 5. ЛОГИКА (БЕЗ ИЗМЕНЕНИЙ, НО ВАЖНАЯ) ---
class InventoryLogic:
    @staticmethod
    async def process_use(interaction: discord.Interaction, item_id: str, target: discord.Member = None):
        """Вся магия использования предмета"""
        
        # Чтобы не зависло, пока думает
        await interaction.response.defer(thinking=True, ephemeral=True)

        user_data = await db.find_user(interaction.user.id)
        current_amount = user_data.get("inventory", {}).get(item_id, 0)

        if current_amount <= 0:
            return await interaction.followup.send(f"❌ Предмет закончился!")

        # Проверка цели (UserSelect может вернуть бота, проверяем)
        if target and target.bot:
            return await interaction.followup.send("🤖 На роботов нельзя.")
        
        if target:
            target_data = await db.find_user(target.id)
            if target_data and target_data.get('inventory', {}).get('shield', 0) > 0:
                await db.add_item(target.id, 'shield', -1)
                await db.add_item(interaction.user.id, item_id, -1)
                # Отправляем в общий чат уведомление о щите (не ephemeral)
                return await interaction.channel.send(f"🛡️ **{target.display_name}** отразил атаку **{interaction.user.display_name}** щитом!")

        msg = ""
        success = False

        try:
            # === HOOK ===
            if item_id == "hook":
                if not interaction.user.voice or not interaction.user.voice.channel:
                    return await interaction.followup.send("❌ Зайдите в войс сами!")
                if not target or not target.voice:
                    return await interaction.followup.send("❌ Цель не в войсе!")
                if interaction.user.voice.channel == target.voice.channel:
                    return await interaction.followup.send("❌ Вы уже в одной комнате.")
                    
                await target.move_to(interaction.user.voice.channel)
                msg = f"🪝 **{interaction.user.name}** притянул **{target.display_name}**!"
                success = True

            # === KICK ===
            elif item_id == "kick":
                if target and target.voice:
                    await target.move_to(None)
                    msg = f"🦶 **{interaction.user.name}** кикнул **{target.display_name}**!"
                    success = True
                else:
                    return await interaction.followup.send("❌ Цель не в войсе.")

            # === MUTE ===
            elif item_id == "mute":
                if target and target.voice:
                    await target.edit(mute=True)
                    msg = f"🤐 **{interaction.user.name}** замутил **{target.display_name}**!"
                    success = True
                    asyncio.create_task(InventoryLogic.unmute_later(target))
                else:
                    return await interaction.followup.send("❌ Цель не в войсе.")

            # === RENAME ===
            elif item_id == "rename":
                if target:
                    await target.edit(nick="Лохматый")
                    msg = f"🤡 **{target.display_name}** переименован!"
                    success = True

            # === STEAL XP ===
            elif item_id == "steal_xp":
                if target:
                    if random.choice([True, False]):
                        target_xp = (await db.find_user(target.id)).get('xp', 0)
                        steal = min(target_xp, 500)
                        if steal > 0:
                            await db.update_user(target.id, {"xp": target_xp - steal})
                            await db.update_user(interaction.user.id, {"xp": user_data['xp'] + steal})
                            msg = f"🔪 **{interaction.user.name}** украл {steal} XP у **{target.display_name}**!"
                            success = True
                        else: return await interaction.followup.send("У него нет XP.")
                    else:
                        fine = 300
                        await db.update_user(interaction.user.id, {"xp": max(0, user_data['xp'] - fine)})
                        msg = f"🚓 **{interaction.user.name}** пойман при краже! Штраф {fine} XP."
                        success = True

            # === XP BOOST ===
            elif item_id == "xp_boost":
                await db.update_user(interaction.user.id, {"xp": user_data['xp'] + 1000})
                msg = f"⚡ **{interaction.user.name}** получил +1000 XP!"
                success = True
            
            # === PASSIVE ===
            elif item_id in ["shield", "ticket_tg", "ticket_nitro", "color_ticket"]:
                return await interaction.followup.send(f"ℹ️ Предмет **{item_id}** работает пассивно или через админа.")

            else:
                 return await interaction.followup.send("❓ Неизвестный предмет.")

        except discord.Forbidden:
             return await interaction.followup.send("🚫 Нет прав (Move/Mute/Rename).")
        except Exception as e:
             return await interaction.followup.send(f"⚠️ Ошибка: {e}")

        if success:
            await db.add_item(interaction.user.id, item_id, -1)
            # Отправляем сообщение
            await interaction.followup.send(msg)

    @staticmethod
    async def unmute_later(member):
        await asyncio.sleep(300)
        try: await member.edit(mute=False)
        except: pass


# --- 6. КОГ INVENTORY ---
class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def item_autocomplete(self, interaction: discord.Interaction, current: str):
        user = await db.find_user(interaction.user.id)
        if not user: return []
        inv = user.get("inventory", {})
        choices = []
        for i_id, amt in inv.items():
            if amt > 0:
                data = ITEMS_DB.get(i_id)
                if not data: continue
                name = f"{data['emoji']} {data['name']} (x{amt})"
                if current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=name, value=i_id))
        return choices[:25]

    @app_commands.command(name="inventory", description="Открыть инвентарь с кнопками")
    async def inventory_cmd(self, interaction: discord.Interaction):
        user = await db.find_user(interaction.user.id)
        if not user:
            return await interaction.response.send_message("❌ Профиль не найден.", ephemeral=True)

        inventory = user.get("inventory", {})
        actual_items = {k: v for k, v in inventory.items() if v > 0}

        if not actual_items:
            return await interaction.response.send_message("🎒 Ваш рюкзак пуст.", ephemeral=True)

        view = InventoryPaginationView(interaction, actual_items)
        await interaction.response.send_message("🎒 **Ваш Инвентарь:**", view=view, ephemeral=True)

    @app_commands.command(name="use", description="Использовать предмет (вручную)")
    @app_commands.describe(item_id="Предмет", target="Цель")
    @app_commands.autocomplete(item_id=item_autocomplete)
    async def use_cmd(self, interaction: discord.Interaction, item_id: str, target: discord.Member = None):
        await InventoryLogic.process_use(interaction, item_id, target)

async def setup(bot):
    await bot.add_cog(Inventory(bot))
