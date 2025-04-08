import os
import time
import requests
import telebot
import logging
import subprocess
from threading import Thread
import routeros_api

# --- Настройка логирования ---
# Указываем путь к файлу логов
log_filename = 'logs/camera_monitor.log'

# Создаем папку для логов, если она не существует
if not os.path.exists('logs'):
    os.makedirs('logs')

# Настраиваем ротацию логов (ежедневно, храним до 7 файлов)
from logging.handlers import TimedRotatingFileHandler
handler = TimedRotatingFileHandler(
    log_filename, when='midnight', interval=1, backupCount=7)
handler.setLevel(logging.DEBUG)
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))

# Создаем объект логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)

# --- Загрузка настроек из переменных окружения ---
# Получаем токен Telegram, ID чата и данные для подключения к Mikrotik
telegram_token = os.getenv('TELEGRAM_TOKEN', '')
chat_id = os.getenv('CHAT_ID', '')
mikrotik_host = os.getenv('MIKROTIK_HOST', '192.168.200.1')
mikrotik_user = os.getenv('MIKROTIK_USER', 'admin')
mikrotik_password = os.getenv('MIKROTIK_PASSWORD', 'your_mikrotik_password')

# --- Инициализация Telegram-бота ---
bot = telebot.TeleBot(telegram_token)

# --- Загрузка данных камер ---
# Читаем файл audmac.txt, содержащий информацию о камерах
# Формат строки: номер аудитории  MAC-адрес  формат запроса
cameras = {}
try:
    with open('audmac.txt', 'r', encoding='utf-8') as file:
        for line in file:
            # Разделяем строку на три части: номер аудитории, MAC-адрес и формат запроса
            parts = line.strip().split(maxsplit=2)
            if len(parts) < 3:
                logger.warning(f"Неправильный формат строки: {line.strip()}")
                continue
            room, mac, req_format = parts
            # Сохраняем данные камеры в словарь
            cameras[room] = {
                'room': room,
                'mac': mac,
                'req_format': req_format,
                'description': f'Камера в аудитории {room}'
            }
except FileNotFoundError as e:
    logger.error(f'Ошибка при чтении файла audmac.txt: {e}')

# --- Глобальные переменные ---
# Флаг для управления мониторингом
monitoring_active = False
monitoring_thread = None

# --- Кэш ARP ---
# Кэш для хранения соответствия MAC-адресов и IP-адресов
arp_cache = {}              # Формат: {mac: ip}
arp_cache_last_update = 0   # Время последнего обновления кэша
arp_cache_update_interval = 86400  # Интервал обновления кэша (24 часа)

# --- Функции для работы с Mikrotik ---
def get_arp_table_from_mikrotik(host, username, password, port=8728):
    """
    Получает ARP-таблицу с Mikrotik через API.
    Возвращает список записей в формате [{"ip": "IP-адрес", "mac": "MAC-адрес"}].
    """
    try:
        # Устанавливаем соединение с Mikrotik
        connection = routeros_api.RouterOsApiPool(
            host, username=username, password=password, port=port, plaintext_login=True)
        api = connection.get_api()
        # Получаем ресурс ARP-таблицы
        arp_resource = api.get_resource('/ip/arp')
        arp_entries = arp_resource.get()
        entries = []
        # Обрабатываем записи ARP-таблицы
        for entry in arp_entries:
            ip = entry.get('address')
            mac = entry.get('mac-address').lower() if entry.get('mac-address') else None
            if ip and mac:
                entries.append({"ip": ip, "mac": mac})
        connection.disconnect()
        logger.debug(f"Получено {len(entries)} записей из ARP таблицы Mikrotik.")
        return entries
    except Exception as e:
        logger.error(f"Ошибка при получении ARP таблицы с Mikrotik: {e}")
        return []

def update_arp_cache():
    """
    Обновляет кэш ARP, получая данные с Mikrotik.
    """
    global arp_cache, arp_cache_last_update
    logger.debug("Обновление ARP кэша через Mikrotik API...")
    arp_entries = get_arp_table_from_mikrotik(mikrotik_host, mikrotik_user, mikrotik_password)
    if arp_entries:
        # Обновляем кэш с новыми данными
        new_cache = {entry['mac']: entry['ip'] for entry in arp_entries}
        arp_cache = new_cache
        arp_cache_last_update = time.time()
        logger.info("ARP кэш успешно обновлён через Mikrotik.")
        return True
    else:
        logger.error("Не удалось обновить ARP кэш через Mikrotik.")
        return False

# --- Функции для работы с камерами ---
def get_ip_from_mac_cached(mac_address):
    """
    Возвращает IP-адрес для заданного MAC из кэша.
    Если кэш пуст или устарел, выполняется обновление.
    """
    global arp_cache, arp_cache_last_update
    mac_colon = mac_address.replace('-', ':').lower()
    # Проверяем, нужно ли обновить кэш
    if not arp_cache or (time.time() - arp_cache_last_update > arp_cache_update_interval):
        logger.debug("ARP кэш пуст или устарел, обновляем его...")
        update_arp_cache()
    # Ищем IP-адрес в кэше
    ip = arp_cache.get(mac_colon)
    if ip:
        logger.debug(f"Найден IP {ip} для MAC {mac_address} в кэше ARP")
    else:
        logger.debug(f"IP для MAC {mac_address} не найден в кэше ARP")
    return ip

def get_camera_url(camera_info):
    """
    Формирует полный URL для камеры на основе IP, полученного из кэша ARP.
    """
    mac = camera_info['mac']
    ip = get_ip_from_mac_cached(mac)
    if not ip:
        logger.error(f"Не удалось определить IP для камеры {camera_info['description']} с MAC {mac}")
        return None
    # Формируем URL камеры
    full_url = camera_info['req_format'] + ip
    logger.debug(f"Определённый URL для камеры {camera_info['description']}: {full_url}")
    return full_url

def check_camera(url):
    try:
        logger.debug(f'Проверка камеры по адресу: {url}')
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            logger.info(f'Камера по адресу {url} доступна.')
            return True
        else:
            logger.warning(f'Камера по адресу {url} вернула статус {response.status_code}.')
    except requests.RequestException as e:
        logger.error(f'Ошибка при проверке камеры {url}: {e}')
    return False

def send_telegram_message(message):
    try:
        logger.debug(f'Отправка сообщения: {message}')
        bot.send_message(chat_id, message)
        logger.info('Сообщение отправлено успешно.')
    except Exception as e:
        logger.error(f'Ошибка при отправке сообщения: {e}')

def monitor_cameras():
    global monitoring_active
    logger.info('Запуск мониторинга камер.')
    while monitoring_active:
        for room, info in cameras.items():
            full_url = get_camera_url(info)
            description = info['description']
            was_online = camera_status[room]['is_online']
            if not full_url:
                camera_status[room]['fail_count'] += 1
                if was_online:
                    send_telegram_message(f'{description} недоступна! Не удалось определить IP адрес.')
                    camera_status[room]['is_online'] = False
                continue

            is_online = check_camera(full_url)
            if is_online:
                camera_status[room] = {'fail_count': 0, 'is_online': True}
                if not was_online:
                    send_telegram_message(f'{description} восстановлена!')
            else:
                camera_status[room]['fail_count'] += 1
                if camera_status[room]['fail_count'] >= 1 and was_online:
                    camera_status[room]['is_online'] = False
                    send_telegram_message(f'{description} недоступна!')
        time.sleep(300)  # Проверка каждые 5 минут
    logger.info('Мониторинг камер остановлен.')
    send_telegram_message('Мониторинг камер остановлен.')

# Инициализация статуса камер
camera_status = {room: {'fail_count': 0, 'is_online': True} for room in cameras}

def arp_cache_updater():
    """
    Фоновый поток для автоматического обновления ARP кэша раз в сутки.
    """
    global monitoring_active
    while monitoring_active:
        time.sleep(arp_cache_update_interval)
        logger.info("Автоматическое обновление ARP кэша (раз в сутки).")
        update_arp_cache()

# Обработчик команды /status
@bot.message_handler(commands=['status'])
def handle_status(message):
    logger.debug('Обработка команды /status')
    working_cameras = []
    non_working_cameras = []

    for room, info in cameras.items():
        full_url = get_camera_url(info)
        description = info['description']
        if full_url and check_camera(full_url):
            working_cameras.append(description)
        else:
            non_working_cameras.append(description)
    
    status_message = "Программа работает" if monitoring_active else "Программа остановлена"
    if non_working_cameras:
        status_message += "\n\nНеработающие камеры:\n" + "\n".join(non_working_cameras)
    else:
        status_message += "\n\nВсе камеры работают"

    bot.send_message(message.chat.id, status_message)
    logger.info('Статус камер отправлен.')

# Обработчик команды /stop
@bot.message_handler(commands=['stop'])
def handle_stop(message):
    global monitoring_active
    logger.info('Обработка команды /stop')
    monitoring_active = False
    send_telegram_message('Бот остановлен.')

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def handle_start(message):
    global monitoring_active, monitoring_thread
    logger.info('Обработка команды /start')
    if not monitoring_active:
        monitoring_active = True
        monitoring_thread = Thread(target=monitor_cameras)
        monitoring_thread.start()
        # Запуск фонового потока для обновления ARP кэша раз в сутки
        arp_updater_thread = Thread(target=arp_cache_updater)
        arp_updater_thread.daemon = True
        arp_updater_thread.start()
        send_telegram_message('Мониторинг камер запущен.')
    else:
        send_telegram_message('Мониторинг уже запущен.')

# Обработчик команды /refresharp для принудительного обновления ARP кэша
@bot.message_handler(commands=['refresharp'])
def handle_refresharp(message):
    logger.info("Обработка команды /refresharp для принудительного обновления ARP кэша")
    if update_arp_cache():
        bot.send_message(message.chat.id, "ARP кэш успешно обновлён.")
    else:
        bot.send_message(message.chat.id, "Ошибка при обновлении ARP кэша.")

# Обработчик команды /getlogs
@bot.message_handler(commands=['getlogs'])
def handle_getlogs(message):
    logger.info('Обработка команды /getlogs')
    if os.path.exists(log_filename):
        try:
            with open(log_filename, 'rb') as log_file:
                bot.send_document(message.chat.id, log_file)
            logger.info('Файл логов отправлен.')
        except Exception as e:
            logger.error(f'Ошибка при отправке файла логов: {e}')
            bot.send_message(message.chat.id, 'Ошибка при отправке файла логов.')
    else:
        logger.warning('Файл логов не найден.')
        bot.send_message(message.chat.id, 'Файл логов не найден.')

def start_bot():
    global monitoring_active
    logger.info('Запуск бота.')
    monitoring_active = True
    monitoring_thread = Thread(target=monitor_cameras)
    monitoring_thread.start()
    try:
        bot.infinity_polling(timeout=2, long_polling_timeout=1)
    except Exception as e:
        logger.error(f'Ошибка при запуске bot.polling: {e}')

if __name__ == "__main__":
    logger.info('Запуск основного цикла программы.')
    bot.remove_webhook()  # Удаляем webhook, если он установлен
    send_telegram_message('Бот запущен!')
    start_bot()


