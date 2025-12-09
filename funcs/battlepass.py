from database import *
levels = {
          1: {'rewards':'сисько','exp_need':100, 'desc': 'первая награда'},
          2: {'rewards':'писько','exp_need': 200, 'desc': 'вторая награда'}, 
          3: {'rewards':'ЧОО', 'exp_need': 300, 'desc': 'третья награда'},  
          4: {'rewards':'роль ахуенск','exp_need': 400, 'desc': 'четвертая награда'}, 
          5: {'rewards':'тачки срачки админки хуинки','exp_need': 500, 'desc': 'пятая награда'}
          }


class Battlepass:
    
    @staticmethod
    async def add_xp(user_id: int, xp_amount: int, username: str):
        user = await Database('Battlepass','users').find_user(user_id=user_id)

        if not user:
            await Database('Battlepass','users').insert_user(user_id=user_id, username=username)
            print(f"Создан новый профиль для {user_id}")
        else:
            # Если есть, обновляем его (добавляем опыт)
            # $inc — оператор инкремента (увеличения)
            print(user['level'])
            print(type(user['level']))
            user_xp = user['xp'] + xp_amount
            # print(levels[user['level']])
            new_level = user['level'] + 1
        
            if user_xp >= levels[new_level]['exp_need']:
                await Database('Battlepass','users').update_user(user_id, {"xp": user_xp, 'level': new_level})
                print(f"Добавлено {xp_amount} опыта пользователю {username}, он достиг {new_level} уровня")
                return True, new_level, username
            else:
                await Database('Battlepass','users').update_user(user_id, {"xp": user_xp})
                print(f"Добавлено {xp_amount} опыта пользователю {user_id}")
                return False
            
        
    # async def reward_
    # async def get_user_progress(user_id: int):
    #     user = await Database('Battlepass')

    async def get_rewards(user_id: int, rewards):
        await Database('Battlepass', 'users').update_user(user_id=user_id, params={'rewards_claimed': rewards})
        asyncio.gather(*[Database('Main_Database', 'users').update_user(user_id=user_id, params=reward) for reward in rewards])

        