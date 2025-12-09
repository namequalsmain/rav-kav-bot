import discord
import time


from discord.ext import commands
from settings import *
from database import *
from funcs.battlepass import *

intents = discord.Intents.default()
intents.voice_states = True # Важно для отслеживания голоса
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Временное хранилище времени входа (в реальном боте лучше использовать Redis или БД)
voice_sessions = {}

@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен и подключен к MongoDB!')


@bot.event
async def on_member_join(member):
    await Database('Main_Database', 'users').insert_new_user(user_id=member.id, username=member.name)




@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel is not None:
        voice_sessions[member.id] = time.time()

    # Пользователь вышел из канала
    elif before.channel is not None and after.channel is None:
        if member.id in voice_sessions:
            start_time = voice_sessions.pop(member.id)
            duration = time.time() - start_time # Время в секундах
            minutes = int(duration / 60)
            
            if minutes >= 0:
                xp_gained = minutes
                # ТУТ КОД ДЛЯ СОХРАНЕНИЯ XP В БАЗУ ДАННЫХ
                status = await Battlepass.add_xp(user_id=member.id, xp_amount=100, username=member.name)
                # И ПРОВЕРКА НА ПОВЫШЕНИЕ УРОВНЯ
                if status:
                    channel = bot.get_channel(1173888168546803744)
                    await channel.send(f'Пользователь {status[2]} достиг {status[1]} уровня!\n<@{status[2]}>, напиши команду /reward чтобы забрать награду')
                # print(bot.get_channel(before.channel))
                
                print(f"{status[2]} провел {minutes} мин. и получил {xp_gained} XP.")

# Команда для просмотра прогресса
@bot.command()
async def battlepass(ctx):
    user = await Database('Battlepass','users').find_user(user_id=ctx.author.id)
    await ctx.send(f'Ваш прогресс боевого пропуска: {user['level']}\nОпыт: {user['xp']} / {levels[user['level']+1]['exp_need']}')
    # Тут нужно достать данные из БД

    # await ctx.send("Ваш уровень БП: 5. Опыт: 450/600. Следующая награда: Роль 'Гладиатор'")
@bot.command()
async def reward(ctx):
    bp_user = await Database('Battlepass','users').find_user(user_id=ctx.author.id)
    user = await Database('Main_Database', 'users').find_user(user_id=ctx.author.id)
    await ctx.send(bp_user['rewards_claimed'])

    # if bp_user['level'] in bp_user['rewards_claimed']:
    #     ctx.send('Вы уже получили награду за этот уровень боевого пропуска.')
    # else:
    #     await Battlepass.get_rewards()
    # print(levels[bp_user['level']])

    # await ctx.send('send')

@bot.command()
async def sync_db(ctx):
    members = ctx.guild.members
    await asyncio.gather(*[Database('Main_Database','users').insert_new_user(user_id=member.id, username=member.name)for member in members if not member.bot])
    await asyncio.gather(*[Database('Battlepass', 'users').insert_user_battlepass(user_id=member.id, username=member.name) for member in members if not member.bot])
    await ctx.send('База данных успешно синхронизирована, пользователи добавлены')

bot.run(BOT_TOKEN)
