import discord
import random
import asyncio
from discord import ui, app_commands
from database import db
from settings import ITEMS_DB, LEVELS, LOG_CHANNEL_ID
from utils.generator import Generator, generate_image_in_thread
from utils.logger import log

# ==========================================
# 🧠 ЛОГИКА ИНВЕНТАРЯ (Inventory Logic)
# ==========================================
class InventoryLogic:
    @staticmethod
    async def process_use(interaction: discord.Interaction, item_id: str, target: discord.Member = None):
        """Обработка использования предмета"""
        
        # Защита от двойного нажатия (если уже ответили)
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True, ephemeral=True)

        user_data = await db.find_user(interaction.user.id)
        current_amount = user_data.get("inventory", {}).get(item_id, 0)

        if current_amount <= 0:
            return await interaction.followup.send(f"❌ Предмет закончился!")

        # Проверки цели
        if target:
            if target.bot:
                return await interaction.followup.send("🤖 На роботов нельзя.")
            
            # Проверка щита у цели
            target_data = await db.find_user(target.id)
            if target_data and target_data.get('inventory', {}).get('shield', 0) > 0:
                await db.add_item(target.id, 'shield', -1)
                await db.add_item(interaction.user.id, item_id, -1)
                return await interaction.channel.send(f"🛡️ **{target.display_name}** отразил атаку **{interaction.user.display_name}** щитом!")

        msg = ""
        success = False

        try:
            # === ЛОГИКА ЭФФЕКТОВ ===
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

            elif item_id == "kick":
                if target and target.voice:
                    await target.move_to(None)
                    msg = f"🦶 **{interaction.user.name}** кикнул **{target.display_name}**!"
                    success = True
                else:
                    return await interaction.followup.send("❌ Цель не в войсе.")

            elif item_id == "mute":
                if target and target.voice:
                    await target.edit(mute=True)
                    msg = f"🤐 **{interaction.user.name}** замутил **{target.display_name}**!"
                    success = True
                    asyncio.create_task(InventoryLogic.unmute_later(target))
                else:
                    return await interaction.followup.send("❌ Цель не в войсе.")

            elif item_id == "rename":
                if target:
                    await target.edit(nick="Лохматый")
                    msg = f"🤡 **{target.display_name}** переименован!"
                    success = True

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

            elif item_id == "xp_boost":
                await db.update_user(interaction.user.id, {"xp": user_data['xp'] + 1000})
                msg = f"⚡ **{interaction.user.name}** получил +1000 XP!"
                success = True
            
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
            await interaction.followup.send(msg)

    @staticmethod
    async def unmute_later(member):
        await asyncio.sleep(300)
        try: await member.edit(mute=False)
        except: pass


# ==========================================
# 🎒 КОМПОНЕНТЫ ИНВЕНТАРЯ (Inventory UI)
# ==========================================

class TargetSelect(ui.UserSelect):
    def __init__(self, item_id, item_name):
        super().__init__(placeholder=f"Выберите цель для {item_name}...", min_values=1, max_values=1)
        self.item_id = item_id

    async def callback(self, interaction: discord.Interaction):
        await InventoryLogic.process_use(interaction, self.item_id, self.values[0])

class TargetSelectView(ui.View):
    def __init__(self, item_id, item_name):
        super().__init__(timeout=60)
        self.add_item(TargetSelect(item_id, item_name))

class ConfirmView(ui.View):
    def __init__(self, item_id, item_name):
        super().__init__(timeout=60)
        self.item_id = item_id
        
    @ui.button(label="Активировать", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await InventoryLogic.process_use(interaction, self.item_id, None)

    @ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="❌ Отменено.", view=None)

class InventoryItemButton(ui.Button):
    def __init__(self, item_id, amount, item_data, row_index, max_len):
        self.item_id = item_id
        raw_name = item_data.get('name', item_id)
        base_label = f"{raw_name} (x{amount})"
        
        # Выравнивание ширины
        needed = max_len - len(base_label)
        padding = "⠀" * int(needed * 1.2)
        final_label = f"{base_label}{padding}"

        emoji = item_data.get('emoji', '📦')
        super().__init__(label=final_label, emoji=emoji, style=discord.ButtonStyle.secondary, row=row_index)

    async def callback(self, interaction: discord.Interaction):
        needs_target = self.item_id in ['kick', 'mute', 'rename', 'steal_xp', 'hook']
        item_name = ITEMS_DB.get(self.item_id, {}).get('name', self.item_id)

        if needs_target:
            view = TargetSelectView(self.item_id, item_name)
            await interaction.response.send_message(f"🎯 Выберите цель для **{item_name}**:", view=view, ephemeral=True)
        else:
            view = ConfirmView(self.item_id, item_name)
            await interaction.response.send_message(f"❓ Использовать **{item_name}**?", view=view, ephemeral=True)

class InventoryPaginationView(ui.View):
    def __init__(self, interaction, inventory_dict):
        super().__init__(timeout=180)
        self.interaction = interaction
        self.user_id = interaction.user.id
        self.items = list(inventory_dict.items())
        self.page = 0
        self.items_per_page = 8
        self.width = 2
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        start = self.page * self.items_per_page
        end = start + self.items_per_page
        current_items = self.items[start:end]

        max_len = 0
        for item_id, amount in current_items:
            data = ITEMS_DB.get(item_id, {})
            name = data.get('name', item_id)
            label_len = len(f"{name} (x{amount})")
            if label_len > max_len: max_len = label_len
        if max_len < 15: max_len = 15

        for i, (item_id, amount) in enumerate(current_items):
            item_data = ITEMS_DB.get(item_id, {})
            row_index = i // self.width 
            self.add_item(InventoryItemButton(item_id, amount, item_data, row_index, max_len))

        if len(self.items) > self.items_per_page:
            total_pages = (len(self.items) - 1) // self.items_per_page + 1
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=4)
            prev_btn.callback = self.prev_callback
            self.add_item(prev_btn)
            
            self.add_item(ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.gray, disabled=True, row=4))
            
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




class SupportModal(ui.Modal, title="Связаться с администрацией"):
    topic = ui.TextInput(
        label="Тема обращения",
        placeholder="Например: Жалоба, Вопрос, Баг",
        max_length=50
    )
    description = ui.TextInput(
        label="Подробное описание",
        style=discord.TextStyle.paragraph,
        placeholder="Опишите вашу проблему...",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Отправляем сообщение в админский канал
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        
        embed = discord.Embed(title="📨 Новое обращение", color=discord.Color.orange())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Тема", value=self.topic.value, inline=False)
        embed.add_field(name="Описание", value=self.description.value, inline=False)
        embed.add_field(name="ID Пользователя", value=interaction.user.id, inline=False)
        
        if log_channel:
            await log_channel.send(embed=embed)
            await interaction.response.send_message("✅ Ваше сообщение отправлено администрации!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ошибка настройки: канал логов не найден.", ephemeral=True)


# --- НОВОЕ: МЕНЮ ПРОФИЛЯ (ОТДЕЛЬНО ОТ БАТТЛПАССА) ---
class ProfileView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id

    # 1. Кнопка инвентаря (Копия логики, так как инвентарь относится и к профилю)
    @ui.button(label="Инвентарь", style=discord.ButtonStyle.primary, emoji="🎒", row=0)
    async def inventory_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Это не твой профиль!", ephemeral=True)

        user = await db.find_user(self.user_id)
        inventory = user.get("inventory", {})
        actual_items = {k: v for k, v in inventory.items() if v > 0}

        if not actual_items:
            return await interaction.response.send_message("🎒 Ваш рюкзак пуст.", ephemeral=True)

        view = InventoryPaginationView(interaction, actual_items)
        await interaction.response.send_message("🎒 **Ваш Инвентарь:**", view=view, ephemeral=True)

    # 2. Кнопка Карта Наград (Тоже полезно видеть в профиле)
    @ui.button(label="Карта наград", style=discord.ButtonStyle.secondary, emoji="🗺️", row=0)
    async def roadmap_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Это не твой профиль!", ephemeral=True)

        await interaction.response.defer(thinking=True, ephemeral=True)
        user = await db.find_user(self.user_id)
        lvl = user.get('level', 0)
        if lvl == 0: lvl = 1
        page = 2 if lvl > 10 else 1
        if lvl > 20: page = 3
        need_xp = LEVELS.get(lvl + 1, {}).get('exp_need', 99999)

        buffer = await generate_image_in_thread(
            Generator.create_roadmap, interaction.user.name, interaction.user.display_avatar.url,
            user.get('xp', 0), need_xp, lvl, page, LEVELS
        )
        if buffer:
            file = discord.File(fp=buffer, filename="roadmap.png")
            view = RoadmapPagination(interaction.user, page, user)
            await interaction.followup.send(file=file, view=view, ephemeral=True)

    # 3. Кнопка Поддержка (Уникальная для профиля)
    @ui.button(label="Поддержка", style=discord.ButtonStyle.success, emoji="⚙️", row=0)
    async def support_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Вы не можете писать в поддержку за другого человека.", ephemeral=True)
        
        await interaction.response.send_modal(SupportModal())

# ==========================================
# 🗺️ ROADMAP (Карта наград)
# ==========================================
class RoadmapPagination(ui.View):
    def __init__(self, user, page, user_data):
        super().__init__(timeout=60)
        self.user = user
        self.page = page
        self.user_data = user_data
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = (self.page <= 1)
        self.children[1].disabled = (self.page >= 3) 

    async def update_image(self, interaction):
        await interaction.response.defer()
        need_xp = LEVELS.get(self.user_data['level'] + 1, {}).get('exp_need', 99999)
        buffer = await generate_image_in_thread(
            Generator.create_roadmap, self.user.name, self.user.display_avatar.url,
            self.user_data['xp'], need_xp, self.user_data['level'], self.page, LEVELS
        )
        file = discord.File(fp=buffer, filename="roadmap.png")
        await interaction.message.edit(attachments=[file], view=self)

    @ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user.id: return
        self.page -= 1
        self.update_buttons()
        await self.update_image(interaction)

    @ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user.id: return
        self.page += 1
        self.update_buttons()
        await self.update_image(interaction)


# ==========================================
# 🎫 BATTLEPASS VIEW (Главное меню)
# ==========================================
class BattlepassView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id

    # 🔥 ТЕПЕРЬ ЭТА КНОПКА ОТКРЫВАЕТ КРАСИВЫЙ ИНВЕНТАРЬ
    @ui.button(label="Инвентарь", style=discord.ButtonStyle.primary, emoji="🎒")
    async def inventory_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Это не твой профиль!", ephemeral=True)

        user = await db.find_user(self.user_id)
        inventory = user.get("inventory", {})
        actual_items = {k: v for k, v in inventory.items() if v > 0}

        if not actual_items:
            return await interaction.response.send_message("🎒 Ваш рюкзак пуст.", ephemeral=True)

        # Вызываем тот же класс, что и в команде /inventory
        view = InventoryPaginationView(interaction, actual_items)
        await interaction.response.send_message("🎒 **Ваш Инвентарь:**", view=view, ephemeral=True)

    @ui.button(label="Карта наград", style=discord.ButtonStyle.secondary, emoji="🗺️")
    async def roadmap_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Это не твой профиль!", ephemeral=True)

        await interaction.response.defer(thinking=True, ephemeral=True)
        user = await db.find_user(self.user_id)
        lvl = user.get('level', 0)
        if lvl == 0: lvl = 1
        page = 2 if lvl > 10 else 1
        if lvl > 20: page = 3
        need_xp = LEVELS.get(lvl + 1, {}).get('exp_need', 99999)

        buffer = await generate_image_in_thread(
            Generator.create_roadmap, interaction.user.name, interaction.user.display_avatar.url,
            user.get('xp', 0), need_xp, lvl, page, LEVELS
        )
        if buffer:
            file = discord.File(fp=buffer, filename="roadmap.png")
            view = RoadmapPagination(interaction.user, page, user)
            await interaction.followup.send(file=file, view=view, ephemeral=True)

    @ui.button(label="Забрать награду", style=discord.ButtonStyle.success, emoji="🎁")
    async def claim_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Это не твой профиль!", ephemeral=True)
            
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        user = await db.find_user(self.user_id)
        current_lvl = user.get('level', 0)
        claimed_list = user.get('rewards_claimed', [0]) 
        
        rewards_text = []
        newly_claimed = []

        for lvl in range(1, current_lvl + 1):
            if lvl not in claimed_list:
                lvl_data = LEVELS.get(lvl)
                if not lvl_data: continue

                reward_type = lvl_data.get('type')
                desc = lvl_data.get('desc', 'Награда')

                if reward_type == 'item':
                    item_id = lvl_data['id']
                    amount = lvl_data.get('amount', 1)
                    await db.add_item(self.user_id, item_id, amount)
                    rewards_text.append(f"🎒 Предмет: **{desc}** (x{amount})")
                
                elif reward_type == 'role':
                    role_id = lvl_data['id']
                    role = interaction.guild.get_role(role_id)
                    if role:
                        try:
                            await interaction.user.add_roles(role)
                            rewards_text.append(f"🎭 Роль: **{role.name}**")
                        except discord.Forbidden:
                            rewards_text.append(f"⚠️ Не смог выдать роль (нет прав)")
                    else:
                        rewards_text.append(f"⚠️ Роль ID {role_id} удалена")

                elif reward_type == 'none':
                    rewards_text.append(f"🎉 Особая награда: **{desc}** (Пиши админу)")

                newly_claimed.append(lvl)

        if newly_claimed:
            updated_list = claimed_list + newly_claimed
            await db.update_user(self.user_id, {"rewards_claimed": updated_list})
            msg = "✅ **Вы получили награды:**\n" + "\n".join(rewards_text)
            await interaction.followup.send(msg)
        else:
            await interaction.followup.send("🤷‍♂️ Наград пока нет!")
