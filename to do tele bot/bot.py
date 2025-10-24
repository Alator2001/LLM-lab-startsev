"""
Telegram-бот для управления задачами.
Принимает задачи, хранит их в JSON, позволяет отмечать как выполненные,
организует по приоритетам и отправляет напоминания.
"""

import logging
import json
import os
import threading
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Загрузка переменных окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Путь к файлу с задачами
TASKS_FILE = 'tasks.json'
# Приоритеты задач
PRIORITIES = ['низкий', 'средний', 'высокий']
# Эмодзи для приоритетов
PRIORITY_EMOJIS = {
    'низкий': '🟢',
    'средний': '🟡',
    'высокий': '🔴'
}

# URL для API CoinGecko
COINGECKO_API_URL = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether&vs_currencies=usd'

# Словарь с названиями криптовалют для отображения
CRYPTO_NAMES = {
    'bitcoin': 'Bitcoin (BTC)',
    'ethereum': 'Ethereum (ETH)',
    'tether': 'Tether (USDT)'
}


class TaskManager:
    """Класс для управления задачами и работы с JSON файлом."""
    
    def __init__(self, filename: str = TASKS_FILE):
        """
        Инициализация менеджера задач.
        
        Args:
            filename: Имя файла для хранения задач в формате JSON
        """
        self.filename = filename
        self.tasks = self.load_tasks()
    
    def load_tasks(self) -> List[Dict]:
        """
        Загружает задачи из JSON файла.
        
        Returns:
            Список задач. Если файл не существует или пустой, возвращает пустой список.
        """
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r', encoding='utf-8') as f:
                    tasks = json.load(f)
                    logger.info(f"Загружено задач: {len(tasks)}")
                    return tasks
            return []
        except Exception as e:
            logger.error(f"Ошибка при загрузке задач: {e}")
            return []
    
    def save_tasks(self):
        """Сохраняет задачи в JSON файл."""
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, ensure_ascii=False, indent=2)
            logger.info(f"Задачи сохранены: {len(self.tasks)} задач")
        except Exception as e:
            logger.error(f"Ошибка при сохранении задач: {e}")
    
    def add_task(self, text: str, user_id: int, priority: str = 'средний', 
                 scheduled_date: Optional[str] = None, scheduled_time: Optional[str] = None) -> int:
        """
        Добавляет новую задачу.
        
        Args:
            text: Текст задачи
            user_id: ID пользователя Telegram
            priority: Приоритет задачи (низкий, средний, высокий)
            scheduled_date: Запланированная дата в формате DD.MM.YYYY
            scheduled_time: Запланированное время в формате HH:MM
        
        Returns:
            ID новой задачи
        """
        task_id = len(self.tasks) + 1
        task = {
            'id': task_id,
            'text': text,
            'user_id': user_id,
            'priority': priority,
            'completed': False,
            'created_at': datetime.now().isoformat(),
            'completed_at': None,
            'scheduled_date': scheduled_date,
            'scheduled_time': scheduled_time
        }
        self.tasks.append(task)
        self.save_tasks()
        logger.info(f"Добавлена задача #{task_id} пользователем {user_id}")
        return task_id
    
    def get_user_tasks(self, user_id: int, completed: Optional[bool] = None) -> List[Dict]:
        """
        Получает задачи пользователя.
        
        Args:
            user_id: ID пользователя Telegram
            completed: Фильтр по статусу выполнения (None - все задачи)
        
        Returns:
            Список задач пользователя
        """
        if completed is None:
            return [task for task in self.tasks if task['user_id'] == user_id]
        return [task for task in self.tasks 
                if task['user_id'] == user_id and task['completed'] == completed]
    
    def mark_task_done(self, user_id: int, task_id: int) -> bool:
        """
        Отмечает задачу как выполненную.
        
        Args:
            user_id: ID пользователя Telegram
            task_id: ID задачи
        
        Returns:
            True если задача найдена и отмечена, False иначе
        """
        for task in self.tasks:
            if task['id'] == task_id and task['user_id'] == user_id:
                task['completed'] = True
                task['completed_at'] = datetime.now().isoformat()
                self.save_tasks()
                logger.info(f"Задача #{task_id} отмечена как выполненная пользователем {user_id}")
                return True
        return False
    
    def get_today_tasks(self, user_id: int) -> List[Dict]:
        """
        Получает задачи, созданные сегодня или запланированные на сегодня.
        
        Args:
            user_id: ID пользователя Telegram
        
        Returns:
            Список задач на сегодня
        """
        today = datetime.now().date()
        today_tasks = []
        for task in self.tasks:
            if task['user_id'] == user_id and task['completed'] == False:
                # Проверяем созданные сегодня
                created_date = datetime.fromisoformat(task['created_at']).date()
                if created_date == today:
                    today_tasks.append(task)
                # Проверяем запланированные на сегодня
                elif task.get('scheduled_date'):
                    try:
                        scheduled_date = datetime.strptime(task['scheduled_date'], '%d.%m.%Y').date()
                        if scheduled_date == today:
                            today_tasks.append(task)
                    except ValueError:
                        continue
        return today_tasks
    
    def get_scheduled_tasks(self) -> List[Dict]:
        """
        Получает все запланированные задачи (невыполненные и с датой/временем).
        
        Returns:
            Список запланированных задач
        """
        scheduled_tasks = []
        for task in self.tasks:
            if not task['completed'] and task.get('scheduled_date') and task.get('scheduled_time'):
                scheduled_tasks.append(task)
        return scheduled_tasks
    
    def get_reminders(self, user_id: int) -> List[Dict]:
        """
        Получает невыполненные задачи для напоминаний.
        
        Args:
            user_id: ID пользователя Telegram
        
        Returns:
            Список невыполненных задач
        """
        return self.get_user_tasks(user_id, completed=False)


# Создаем экземпляр менеджера задач
task_manager = TaskManager()

# Глобальная переменная для хранения Application и event loop
app_instance = None
main_loop = None


def format_task(task: Dict) -> str:
    """
    Форматирует задачу для отображения в сообщении.
    
    Args:
        task: Словарь с данными задачи
    
    Returns:
        Отформатированная строка с задачей
    """
    status = "✅" if task['completed'] else "⏳"
    priority_emoji = PRIORITY_EMOJIS.get(task['priority'], '⚪')
    created = datetime.fromisoformat(task['created_at']).strftime('%d.%m.%Y %H:%M')
    
    result = f"{status} {priority_emoji} [{task['priority']}] #{task['id']}: {task['text']}\n"
    result += f"   📅 Создана: {created}"
    
    # Добавляем информацию о запланированной дате и времени
    if task.get('scheduled_date'):
        result += f"\n   📆 Запланирована: {task['scheduled_date']}"
        if task.get('scheduled_time'):
            result += f" в {task['scheduled_time']}"
    
    if task['completed'] and task['completed_at']:
        completed = datetime.fromisoformat(task['completed_at']).strftime('%d.%m.%Y %H:%M')
        result += f"\n   ✅ Выполнена: {completed}"
    
    return result


async def get_crypto_prices() -> Optional[Dict]:
    """
    Получает актуальные курсы криптовалют через API CoinGecko.
    
    Returns:
        Словарь с данными о курсах криптовалют или None в случае ошибки
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(COINGECKO_API_URL)
            if response.status_code == 200:
                data = response.json()
                logger.info("Успешно получены курсы криптовалют")
                return data
            else:
                logger.error(f"Ошибка API CoinGecko: статус {response.status_code}")
                return None
    except httpx.TimeoutException:
        logger.error("Таймаут при запросе к API CoinGecko")
        return None
    except httpx.RequestError as e:
        logger.error(f"Ошибка сети при запросе к API CoinGecko: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при получении курсов: {e}")
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start.
    Приветствует пользователя и объясняет функционал бота.
    """
    welcome_message = """
👋 Привет! Я бот для управления задачами.

📋 Что я умею:
• Добавлять задачи с приоритетами (низкий, средний, высокий)
• Планировать задачи на определенную дату и время
• Отмечать задачи как выполненные
• Показывать список задач на сегодня
• Отправлять напоминания о невыполненных задачах
• Показывать актуальные курсы криптовалют 💰

📝 Основные команды:
/add <задача> - добавить новую задачу
/schedule <задача> <дата> <время> - запланировать задачу
/today - показать задачи на сегодня
/list - показать все активные задачи
/completed - показать выполненные задачи
/done <ID> - отметить задачу как выполненную
/crypto - показать курсы криптовалют
/help - показать справку

Начните работу, отправив команду /add <ваша задача>!
    """
    await update.message.reply_text(welcome_message)
    logger.info(f"Пользователь {update.effective_user.id} запустил бота")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /help.
    Выводит справку по использованию бота.
    """
    help_text = """
📚 Справка по командам:

/add <задача> <приоритет>
   Добавляет новую задачу
   Пример: /add Купить молоко низкий
   Приоритеты: низкий, средний, высокий
   По умолчанию: средний

/schedule <задача> <дата> <время> <приоритет>
   Планирует задачу на определенную дату и время
   Пример: /schedule Встреча с клиентом 20.01.2024 15:00 высокий
   Формат даты: DD.MM.YYYY
   Формат времени: HH:MM
   Приоритет по умолчанию: средний

/today
   Показывает все задачи на сегодня

/list
   Показывает все активные (невыполненные) задачи

/completed
   Показывает все выполненные задачи

/done <ID>
   Отмечает задачу как выполненную
   Пример: /done 5

/crypto
   Показывает актуальные курсы криптовалют (Bitcoin, Ethereum, Tether)

/help
   Показывает эту справку

💡 Совет: Вы можете просто написать текст задачи в чат,
и бот спросит у вас приоритет!
    """
    await update.message.reply_text(help_text)
    logger.info(f"Пользователь {update.effective_user.id} запросил справку")


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /crypto.
    Показывает актуальные курсы топ-3 криптовалют.
    """
    user_id = update.effective_user.id
    
    # Отправляем сообщение о загрузке
    loading_message = await update.message.reply_text("⏳ Загружаю курсы криптовалют...")
    
    # Получаем курсы криптовалют
    crypto_data = await get_crypto_prices()
    
    # Проверяем, получены ли данные
    if crypto_data is None:
        await loading_message.edit_text(
            "❌ Не удалось получить курсы криптовалют.\n\n"
            "Возможные причины:\n"
            "• Проблемы с интернет-соединением\n"
            "• API CoinGecko временно недоступен\n\n"
            "Попробуйте позже."
        )
        logger.warning(f"Пользователь {user_id} не смог получить курсы криптовалют")
        return
    
    # Формируем сообщение с курсами
    message = "💰 Актуальные курсы криптовалют:\n\n"
    
    # Проверяем наличие данных для каждой криптовалюты
    for crypto_id, crypto_name in CRYPTO_NAMES.items():
        if crypto_id in crypto_data and 'usd' in crypto_data[crypto_id]:
            price = crypto_data[crypto_id]['usd']
            # Форматируем цену
            if price >= 1:
                formatted_price = f"{price:,.2f}".replace(',', ' ')
            else:
                formatted_price = f"{price:.4f}"
            message += f"{crypto_name}: {formatted_price} USD\n"
        else:
            logger.warning(f"Нет данных для {crypto_id}")
            message += f"{crypto_name}: Данные недоступны\n"
    
    message += "\n📊 Данные предоставлены CoinGecko"
    
    # Отправляем сообщение с курсами
    await loading_message.edit_text(message)
    logger.info(f"Пользователь {user_id} запросил курсы криптовалют")


async def add_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /add.
    Добавляет новую задачу.
    """
    user_id = update.effective_user.id
    
    # Проверяем, есть ли аргументы
    if not context.args:
        await update.message.reply_text(
            "❌ Пожалуйста, укажите задачу!\n"
            "Пример: /add Купить молоко низкий"
        )
        return
    
    # Парсим аргументы
    args = ' '.join(context.args)
    
    # Проверяем, есть ли приоритет в конце
    priority = 'средний'
    words = args.split()
    
    if len(words) > 1 and words[-1].lower() in PRIORITIES:
        priority = words[-1].lower()
        task_text = ' '.join(words[:-1])
    else:
        task_text = args
    
    # Добавляем задачу
    task_id = task_manager.add_task(task_text, user_id, priority)
    
    priority_emoji = PRIORITY_EMOJIS.get(priority, '⚪')
    response = f"✅ Задача добавлена!\n\n{priority_emoji} [{priority}] #{task_id}: {task_text}"
    
    await update.message.reply_text(response)
    logger.info(f"Пользователь {user_id} добавил задачу #{task_id}")


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /today.
    Показывает задачи на сегодня.
    """
    user_id = update.effective_user.id
    today_tasks = task_manager.get_today_tasks(user_id)
    
    if not today_tasks:
        await update.message.reply_text("📅 У вас нет задач на сегодня!")
        return
    
    message = "📅 Задачи на сегодня:\n\n"
    for task in today_tasks:
        message += f"{format_task(task)}\n\n"
    
    await update.message.reply_text(message)
    logger.info(f"Пользователь {user_id} запросил задачи на сегодня")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /list.
    Показывает все активные задачи.
    """
    user_id = update.effective_user.id
    active_tasks = task_manager.get_user_tasks(user_id, completed=False)
    
    if not active_tasks:
        await update.message.reply_text("✅ У вас нет активных задач!")
        return
    
    message = "📋 Активные задачи:\n\n"
    for task in active_tasks:
        message += f"{format_task(task)}\n\n"
    
    await update.message.reply_text(message)
    logger.info(f"Пользователь {user_id} запросил список активных задач")


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /schedule.
    Планирует задачу на определенную дату и время.
    """
    user_id = update.effective_user.id
    
    # Проверяем, есть ли аргументы
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "❌ Пожалуйста, укажите задачу, дату и время!\n\n"
            "Пример: /schedule Встреча с клиентом 20.01.2024 15:00 высокий\n\n"
            "Формат даты: DD.MM.YYYY\n"
            "Формат времени: HH:MM"
        )
        return
    
    args = ' '.join(context.args)
    words = args.split()
    
    # Проверяем последний элемент на приоритет
    priority = 'средний'
    if len(words) >= 3 and words[-1].lower() in PRIORITIES:
        priority = words[-1].lower()
        args_to_parse = ' '.join(words[:-1])
    else:
        args_to_parse = args
    
    # Парсим дату и время
    parts = args_to_parse.rsplit(' ', 2)
    
    if len(parts) < 3:
        await update.message.reply_text(
            "❌ Неверный формат! Используйте:\n"
            "/schedule <задача> <дата> <время>\n"
            "Пример: /schedule Встреча с клиентом 20.01.2024 15:00"
        )
        return
    
    task_text = parts[0]
    scheduled_date = parts[1]
    scheduled_time = parts[2]
    
    # Проверяем формат даты
    try:
        datetime.strptime(scheduled_date, '%d.%m.%Y')
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты! Используйте DD.MM.YYYY\n"
            "Пример: 20.01.2024"
        )
        return
    
    # Проверяем формат времени
    try:
        datetime.strptime(scheduled_time, '%H:%M')
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени! Используйте HH:MM\n"
            "Пример: 15:00"
        )
        return
    
    # Добавляем задачу
    task_id = task_manager.add_task(task_text, user_id, priority, scheduled_date, scheduled_time)
    
    priority_emoji = PRIORITY_EMOJIS.get(priority, '⚪')
    response = f"✅ Задача запланирована!\n\n"
    response += f"{priority_emoji} [{priority}] #{task_id}: {task_text}\n"
    response += f"📆 Дата: {scheduled_date} в {scheduled_time}"
    
    await update.message.reply_text(response)
    logger.info(f"Пользователь {user_id} запланировал задачу #{task_id} на {scheduled_date} {scheduled_time}")


async def send_reminders_sync():
    """
    Синхронная версия функции отправки напоминаний.
    Без параметра context для использования в потоке.
    """
    if not app_instance:
        return
        
    now = datetime.now()
    scheduled_tasks = task_manager.get_scheduled_tasks()
    
    for task in scheduled_tasks:
        if task.get('scheduled_date') and task.get('scheduled_time'):
            try:
                # Парсим дату и время задачи
                task_date = datetime.strptime(task['scheduled_date'], '%d.%m.%Y').date()
                task_time = datetime.strptime(task['scheduled_time'], '%H:%M').time()
                task_datetime = datetime.combine(task_date, task_time)
                
                # Проверяем, наступило ли время выполнения (с точностью до минуты)
                if now >= task_datetime:
                    # Отправляем напоминание
                    priority_emoji = PRIORITY_EMOJIS.get(task['priority'], '⚪')
                    message = f"🔔 Напоминание о задаче!\n\n"
                    message += f"{priority_emoji} [{task['priority']}] #{task['id']}: {task['text']}\n"
                    message += f"📆 Запланировано: {task['scheduled_date']} в {task['scheduled_time']}"
                    
                    await app_instance.bot.send_message(
                        chat_id=task['user_id'],
                        text=message
                    )
                    
                    logger.info(f"Отправлено напоминание о задаче #{task['id']} пользователю {task['user_id']}")
                    
                    # Удаляем запланированную дату и время, чтобы не отправлять повторно
                    # (задача остается активной, но без напоминания)
                    task['scheduled_date'] = None
                    task['scheduled_time'] = None
                    task_manager.save_tasks()
                    
            except ValueError as e:
                logger.error(f"Ошибка при проверке задачи #{task['id']}: {e}")
                continue


async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    """
    Функция для отправки напоминаний о запланированных задачах.
    Проверяет задачи, у которых наступило время выполнения.
    """
    if not app_instance:
        return
        
    now = datetime.now()
    scheduled_tasks = task_manager.get_scheduled_tasks()
    
    for task in scheduled_tasks:
        if task.get('scheduled_date') and task.get('scheduled_time'):
            try:
                # Парсим дату и время задачи
                task_date = datetime.strptime(task['scheduled_date'], '%d.%m.%Y').date()
                task_time = datetime.strptime(task['scheduled_time'], '%H:%M').time()
                task_datetime = datetime.combine(task_date, task_time)
                
                # Проверяем, наступило ли время выполнения (с точностью до минуты)
                if now >= task_datetime:
                    # Отправляем напоминание
                    priority_emoji = PRIORITY_EMOJIS.get(task['priority'], '⚪')
                    message = f"🔔 Напоминание о задаче!\n\n"
                    message += f"{priority_emoji} [{task['priority']}] #{task['id']}: {task['text']}\n"
                    message += f"📆 Запланировано: {task['scheduled_date']} в {task['scheduled_time']}"
                    
                    await app_instance.bot.send_message(
                        chat_id=task['user_id'],
                        text=message
                    )
                    
                    logger.info(f"Отправлено напоминание о задаче #{task['id']} пользователю {task['user_id']}")
                    
                    # Удаляем запланированную дату и время, чтобы не отправлять повторно
                    # (задача остается активной, но без напоминания)
                    task['scheduled_date'] = None
                    task['scheduled_time'] = None
                    task_manager.save_tasks()
                    
            except ValueError as e:
                logger.error(f"Ошибка при проверке задачи #{task['id']}: {e}")
                continue


def check_reminders_periodically():
    """
    Периодическая проверка напоминаний с использованием threading.Timer.
    """
    def run_check():
        try:
            if app_instance and main_loop:
                # Запускаем корутину в основном event loop через run_coroutine_threadsafe
                future = asyncio.run_coroutine_threadsafe(send_reminders_sync(), main_loop)
                # Ждем завершения (с таймаутом)
                try:
                    future.result(timeout=10)
                    logger.info("Проверка напоминаний выполнена")
                except Exception as e:
                    logger.error(f"Ошибка при выполнении проверки напоминаний: {e}")
        except Exception as e:
            logger.error(f"Ошибка в проверке напоминаний: {e}")
        finally:
            # Планируем следующую проверку через 60 секунд
            timer = threading.Timer(60.0, run_check)
            timer.daemon = True
            timer.start()
    
    # Запускаем первую проверку через 10 секунд
    timer = threading.Timer(10.0, run_check)
    timer.daemon = True
    timer.start()
    logger.info("Запущен планировщик проверки напоминаний")


async def completed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /completed.
    Показывает все выполненные задачи.
    """
    user_id = update.effective_user.id
    completed_tasks = task_manager.get_user_tasks(user_id, completed=True)
    
    if not completed_tasks:
        await update.message.reply_text("✅ У вас нет выполненных задач!")
        return
    
    message = "✅ Выполненные задачи:\n\n"
    for task in completed_tasks:
        message += f"{format_task(task)}\n\n"
    
    await update.message.reply_text(message)
    logger.info(f"Пользователь {user_id} запросил список выполненных задач")


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /done.
    Отмечает задачу как выполненную.
    """
    user_id = update.effective_user.id
    
    # Проверяем, есть ли аргумент с ID задачи
    if not context.args:
        await update.message.reply_text(
            "❌ Пожалуйста, укажите ID задачи!\n"
            "Пример: /done 5"
        )
        return
    
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID задачи должен быть числом!")
        return
    
    # Отмечаем задачу как выполненную
    if task_manager.mark_task_done(user_id, task_id):
        await update.message.reply_text(f"✅ Задача #{task_id} отмечена как выполненная!")
        logger.info(f"Пользователь {user_id} отметил задачу #{task_id} как выполненную")
    else:
        await update.message.reply_text(
            f"❌ Задача #{task_id} не найдена или уже выполнена!"
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик текстовых сообщений (не команд).
    Если пользователь просто пишет текст, предлагает добавить задачу.
    """
    user_id = update.effective_user.id
    text = update.message.text
    
    # Если сообщение похоже на команду, игнорируем
    if text.startswith('/'):
        await update.message.reply_text(
            "❌ Неизвестная команда. Используйте /help для справки."
        )
        return
    
    # Предлагаем добавить задачу
    response = f"Вы хотите добавить задачу?\n\n"
    response += f"📝 Текст: {text}\n\n"
    response += "📌 Выберите приоритет:\n"
    response += "1️⃣ Низкий\n"
    response += "2️⃣ Средний\n"
    response += "3️⃣ Высокий\n\n"
    response += "Или используйте команду:\n"
    response += f"/add {text} низкий"
    
    await update.message.reply_text(response)
    logger.info(f"Пользователь {user_id} отправил текстовое сообщение")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик ошибок.
    Логирует ошибки и уведомляет пользователя.
    """
    logger.error(f"Ошибка при обработке update: {update}")
    logger.error(f"Context: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Попробуйте позже или используйте /help для справки."
        )


def main():
    """
    Главная функция для запуска бота.
    """
    # Получаем токен из переменных окружения
    bot_token = os.getenv('BOT_TOKEN')
    
    if not bot_token:
        logger.error("BOT_TOKEN не найден в переменных окружения!")
        logger.error("Создайте файл .env с переменной BOT_TOKEN")
        return
    
    # Создаем приложение
    application = Application.builder().token(bot_token).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_task_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("completed", completed_command))
    application.add_handler(CommandHandler("crypto", crypto_command))
    
    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    # Регистрируем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Сохраняем глобальную ссылку на application
    global app_instance, main_loop
    
    # Получаем event loop до запуска
    main_loop = asyncio.get_event_loop()
    app_instance = application
    
    # Запускаем поток проверки напоминаний
    check_reminders_periodically()
    
    # Запускаем бота
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

