import motor.motor_asyncio # Импортируем асинхронную библиотеку
import asyncio
import time

from settings import DB_PASS, DB_USERNAME



MONGO_URL = f"mongodb+srv://{DB_USERNAME}:{DB_PASS}@cluster0.1tonrmv.mongodb.net/?appName=Cluster0" 



class Database:


    async def find_user(self,user_id):
        #print('bebra')
        self.user = await self.users_collection.find_one({"_id": user_id})
        return self.user
        #print(user)
    
    async def insert_new_user(self, user_id, username):
        new_user = {
            "_id" : user_id,
            "username" : username,
            "reg_date" : time.time(),
            "referals" : 0,
            "inventory" : [],
            "rank" : 'Новичок'
        }
        try:
            await self.users_collection.insert_one(new_user)
        except:
            pass

    async def insert_user_battlepass(self,user_id, username):
        new_user = {
                "_id": user_id,
                "username": username,
                "xp": 0,
                "level": 0,
                "rewards_claimed": [],
            }
        try:
            await self.users_collection.insert_one(new_user)
        except:
            pass
            

    async def update_user(self,user_id,params: dict):
        
        await asyncio.gather(*[self.users_collection.update_one(
                    {"_id": user_id},
                    {"$set": {(param): params[param]}}
                ) for param in params.keys()])


    def __init__(self, db_name, table):
        cluster = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
        db = cluster[db_name]
        self.users_collection = db[table]



    


    

