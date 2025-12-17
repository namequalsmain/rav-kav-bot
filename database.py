import motor.motor_asyncio
import time
from settings import MONGO_URL

class DatabaseManager:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
        # Используем одну базу данных, но разные коллекции
        self.db = self.client['Main_Database'] 
        self.users = self.db['users']
    async def find_user(self, user_id):
        return await self.users.find_one({"_id": user_id})

    async def create_user(self, user_id, username):
        new_user = {
            "_id": user_id,
            "username": username,
            "reg_date": time.time(),
            "xp": 0,
            "level": 0,
            "rank": "Новичок",
            "inventory": {},
            "rewards_claimed": [0],
            "settings": {"lang": "ru", "ephermal": True},
        }
        try:
            await self.users.insert_one(new_user)
            return new_user
        except:
            return None # Пользователь уже существует

    async def update_user(self, user_id, data: dict):
        """Обновляет любые поля пользователя"""
        await self.users.update_one({"_id": user_id}, {"$set": data})

    async def add_item(self, user_id: int, item_id: str, amount: int):
        """Добавляет предмет (или отнимает, если amount < 0)"""
        await self.users.update_one(
            {"_id": user_id},
            {"$inc": {f"inventory.{item_id}": amount}},
            upsert=True
        )
    async def toggle_setting(self, user_id, setting_key):
        """Переключает настройку (True <-> False) и возвращает новое состояние"""
        user = await self.find_user(user_id)
        
        # Получаем текущие настройки (по умолчанию пустой словарь)
        settings = user.get("settings", {})
        
        # Инвертируем значение (если настройки нет, считаем что она была True, ставим False, или наоборот)
        # Давай договоримся: по умолчанию все True (включено).
        # Значит, если ключа нет -> ставим False. Если есть True -> False.
        current_value = settings.get(setting_key, True) 
        new_value = not current_value
        
        # Обновляем вложенное поле через dot notation
        await self.users.update_one(
            {"_id": user_id},
            {"$set": {f"settings.{setting_key}": new_value}}
        )
        
        return new_value

    async def get_settings(self, user_id):
        """Возвращает словарь настроек"""
        user = await self.find_user(user_id)
        if not user: return {}
        return user.get("settings", {})
# Создаем экземпляр, который будем импортировать в других файлах
db = DatabaseManager()