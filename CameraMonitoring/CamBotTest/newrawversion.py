import os
import time
import asyncio
import aiohttp
import logging
import routeros_api
from dataclasses import dataclass
from threading import Thread, Event
from typing import Dict, Optional, List
from pathlib import Path

import aiogram
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- Конфигурация ---
@dataclass
class Config:
    """Класс для управления конфигурацией приложения"""
    telegram_token: str
    chat_id: str
    mikrotik_host: str
    mikrotik_user: str
    mikrotik_password: str
    mikrotik_port: int = 8728
    camera_file: str = 'audmac.txt'
    log_file: str = 'logs/camera_monitor.log'
    
    # Интервалы проверки (в секундах)
    camera_check_interval: int = 300  # 5 минут
    arp_cache_update_interval: int = 86400  # 24 часа
    
    # Настройки повторных попыток
    camera_retry_attempts: int = 3
    camera_retry_delay: int = 5
    camera_request_timeout: int = 10
    
    # Порог ошибок для алертов
    camera_fail_threshold: int = 3
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Создает конфигурацию из переменных окружения с валидацией"""
        required_vars = [
            'TELEGRAM_TOKEN', 'CHAT_ID', 'MIKROTIK_HOST', 
            'MIKROTIK_USER', 'MIKROTIK_PASSWORD'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(
                f"Отсутствуют обязательные переменные окружения: {missing_vars}"
            )
        
        return cls(
            telegram_token=os.getenv('TELEGRAM_TOKEN'),
            chat_id=os.getenv('CHAT_ID'),
            mikrotik_host=os.getenv('MIKROTIK_HOST', '192.168.200.1'),
            mikrotik_user=os.getenv('MIKROTIK_USER', 'admin'),
            mikrotik_password=os.getenv('MIKROTIK_PASSWORD'),
            mikrotik_port=int(os.getenv('MIKROTIK_PORT', '8728')),
            camera_file=os.getenv('CAMERA_FILE', 'audmac.txt'),
            log_file=os.getenv('LOG_FILE', 'logs/camera_monitor.log'),
            camera_check_interval=int(os.getenv('CAMERA_CHECK_INTERVAL', '300')),
            arp_cache_update_interval=int(os.getenv('ARP_CACHE_UPDATE_INTERVAL', '86400')),
            camera_retry_attempts=int(os.getenv('CAMERA_RETRY_ATTEMPTS', '3')),
            camera_retry_delay=int(os.getenv('CAMERA_RETRY_DELAY', '5')),
            camera_request_timeout=int(os.getenv('CAMERA_REQUEST_TIMEOUT', '10')),
            camera_fail_threshold=int(os.getenv('CAMERA_FAIL_THRESHOLD', '3'))
        )

# --- Настройка логирования ---
def setup_logging(log_file: str) -> logging.Logger:
    """Настраивает логирование с ротацией файлов"""
    log_dir = Path(log_file).parent
    log_dir.mkdir(exist_ok=True)
    
    from logging.handlers import TimedRotatingFileHandler
    
    handler = TimedRotatingFileHandler(
        log_file, when='midnight', interval=1, backupCount=7
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    
    return logger

# --- Работа с ARP-кэшем ---
class ARPCache:
    """Класс для управления ARP-кэшем Mikrotik"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._cache: Dict[str, str] = {}
        self._last_update = 0
        
    def get_ip_from_mac(self, mac_address: str) -> Optional[str]:
        """Возвращает IP-адрес для заданного MAC из кэша"""
        mac_colon = mac_address.replace('-', ':').lower()
        
        if self._should_update_cache():
            self.update_cache()
            
        ip = self._cache.get(mac_colon)
        if ip:
            self.logger.debug(f"Найден IP {ip} для MAC {mac_address}")
        else:
            self.logger.debug(f"IP для MAC {mac_address} не найден в кэше")
        
        return ip
    
    def _should_update_cache(self) -> bool:
        """Проверяет, нужно ли обновить кэш"""
        return (not self._cache or 
                time.time() - self._last_update > self.config.arp_cache_update_interval)
    
    def update_cache(self) -> bool:
        """Обновляет кэш ARP из Mikrotik"""
        try:
            self.logger.debug("Обновление ARP кэша через Mikrotik API...")
            
            arp_entries = self._get_arp_table_from_mikrotik()
            if arp_entries:
                self._cache = {entry['mac']: entry['ip'] for entry in arp_entries}
                self._last_update = time.time()
                self.logger.info("ARP кэш успешно обновлён")
                return True
            else:
                self.logger.error("Не удалось получить данные ARP таблицы")
                return False
                
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении ARP кэша: {e}")
            return False
    
    def _get_arp_table_from_mikrotik(self) -> List[Dict[str, str]]:
        """Получает ARP-таблицу с Mikrotik через API"""
        try:
            connection = routeros_api.RouterOsApiPool(
                self.config.mikrotik_host,
                username=self.config.mikrotik_user,
                password=self.config.mikrotik_password,
                port=self.config.mikrotik_port,
                plaintext_login=True
            )
            
            api = connection.get_api()
            arp_resource = api.get_resource('/ip/arp')
            arp_entries = arp_resource.get()
            
            entries = []
            for entry in arp_entries:
                ip = entry.get('address')
                mac = entry.get('mac-address')
                if ip and mac:
                    entries.append({"ip": ip, "mac": mac.lower()})
            
            connection.disconnect()
            self.logger.debug(f"Получено {len(entries)} записей из ARP таблицы")
            return entries
            
        except Exception as e:
            self.logger.error(f"Ошибка подключения к Mikrotik: {e}")
            return []

# --- Работа с камерами ---
@dataclass
class CameraInfo:
    """Информация о камере"""
    room: str
    mac: str
    req_format: str
    description: str

@dataclass
class CameraStatus:
    """Статус камеры"""
    is_online: bool = True
    fail_count: int = 0
    last_check: float = 0

class CameraManager:
    """Класс для управления камерами"""
    
    def __init__(self, config: Config, arp_cache: ARPCache, logger: logging.Logger):
        self.config = config
        self.arp_cache = arp_cache
        self.logger = logger
        self.cameras: Dict[str, CameraInfo] = {}
        self.camera_status: Dict[str, CameraStatus] = {}
        
    def load_cameras(self) -> bool:
        """Загружает список камер из файла"""
        try:
            if not Path(self.config.camera_file).exists():
                raise FileNotFoundError(f"Файл камер {self.config.camera_file} не найден")
            
            with open(self.config.camera_file, 'r', encoding='utf-8') as file:
                for line_num, line in enumerate(file, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                        
                    parts = line.split(maxsplit=2)
                    if len(parts) < 3:
                        self.logger.warning(
                            f"Неправильный формат строки {line_num}: {line}"
                        )
                        continue
                    
                    room, mac, req_format = parts
                    camera_info = CameraInfo(
                        room=room,
                        mac=mac,
                        req_format=req_format,
                        description=f'Камера в аудитории {room}'
                    )
                    
                    self.cameras[room] = camera_info
                    self.camera_status[room] = CameraStatus()
            
            if not self.cameras:
                raise ValueError("Не найдено ни одной камеры в файле")
            
            self.logger.info(f"Загружено {len(self.cameras)} камер")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке камер: {e}")
            return False
    
    def get_camera_url(self, camera_info: CameraInfo) -> Optional[str]:
        """Формирует URL для камеры"""
        ip = self.arp_cache.get_ip_from_mac(camera_info.mac)
        if not ip:
            return None
        
        return camera_info.req_format + ip
    
    async def check_camera_async(self, url: str) -> bool:
        """Асинхронная проверка доступности камеры с повторными попытками"""
        for attempt in range(self.config.camera_retry_attempts):
            try:
                timeout = aiohttp.ClientTimeout(total=self.config.camera_request_timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            self.logger.debug(f"Камера {url} доступна (попытка {attempt + 1})")
                            return True
                        else:
                            self.logger.warning(
                                f"Камера {url} вернула статус {response.status} (попытка {attempt + 1})"
                            )
                            
            except asyncio.TimeoutError:
                self.logger.warning(f"Таймаут при проверке камеры {url} (попытка {attempt + 1})")
            except Exception as e:
                self.logger.warning(f"Ошибка при проверке камеры {url} (попытка {attempt + 1}): {e}")
            
            if attempt < self.config.camera_retry_attempts - 1:
                await asyncio.sleep(self.config.camera_retry_delay)
        
        self.logger.error(f"Камера {url} недоступна после {self.config.camera_retry_attempts} попыток")
        return False

# --- Мониторинг камер ---
class CameraMonitor:
    """Класс для мониторинга камер"""
    
    def __init__(self, config: Config, camera_manager: CameraManager, 
                 arp_cache: ARPCache, logger: logging.Logger):
        self.config = config
        self.camera_manager = camera_manager
        self.arp_cache = arp_cache
        self.logger = logger
        self.stop_event = Event()
        self.monitor_thread: Optional[Thread] = None
        self.arp_update_thread: Optional[Thread] = None
        
        # Колбэк для отправки сообщений
        self.message_callback: Optional[callable] = None
    
    def set_message_callback(self, callback: callable):
        """Устанавливает колбэк для отправки сообщений"""
        self.message_callback = callback
    
    def start_monitoring(self):
        """Запускает мониторинг"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.logger.warning("Мониторинг уже запущен")
            return False
        
        if not self.camera_manager.load_cameras():
            self.logger.error("Не удалось загрузить камеры")
            return False
        
        self.stop_event.clear()
        
        # Запуск потока мониторинга камер
        self.monitor_thread = Thread(target=self._monitor_cameras_loop, daemon=True)
        self.monitor_thread.start()
        
        # Запуск потока обновления ARP кэша
        self.arp_update_thread = Thread(target=self._arp_update_loop, daemon=True)
        self.arp_update_thread.start()
        
        self.logger.info("Мониторинг камер запущен")
        return True
    
    def stop_monitoring(self):
        """Останавливает мониторинг"""
        self.stop_event.set()
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        if self.arp_update_thread and self.arp_update_thread.is_alive():
            self.arp_update_thread.join(timeout=5)
        
        self.logger.info("Мониторинг камер остановлен")
    
    def _monitor_cameras_loop(self):
        """Основной цикл мониторинга камер"""
        while not self.stop_event.is_set():
            try:
                asyncio.run(self._check_all_cameras())
            except Exception as e:
                self.logger.error(f"Ошибка в цикле мониторинга: {e}")
            
            self.stop_event.wait(self.config.camera_check_interval)
    
    async def _check_all_cameras(self):
        """Проверяет все камеры асинхронно"""
        tasks = []
        for room, camera_info in self.camera_manager.cameras.items():
            task = self._check_single_camera(room, camera_info)
            tasks.append(task)
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _check_single_camera(self, room: str, camera_info: CameraInfo):
        """Проверяет одну камеру"""
        try:
            status = self.camera_manager.camera_status[room]
            was_online = status.is_online
            
            # Получаем URL камеры
            camera_url = self.camera_manager.get_camera_url(camera_info)
            if not camera_url:
                self._handle_camera_failure(room, camera_info, was_online, 
                                           "Не удалось определить IP адрес")
                return
            
            # Проверяем доступность камеры
            is_online = await self.camera_manager.check_camera_async(camera_url)
            
            if is_online:
                self._handle_camera_success(room, camera_info, was_online)
            else:
                self._handle_camera_failure(room, camera_info, was_online, 
                                           "Камера недоступна")
                                           
        except Exception as e:
            self.logger.error(f"Ошибка при проверке камеры {room}: {e}")
    
    def _handle_camera_success(self, room: str, camera_info: CameraInfo, was_online: bool):
        """Обрабатывает успешную проверку камеры"""
        status = self.camera_manager.camera_status[room]
        status.fail_count = 0
        status.is_online = True
        status.last_check = time.time()
        
        if not was_online:
            message = f"{camera_info.description} восстановлена!"
            self._send_message(message)
            self.logger.info(message)
    
    def _handle_camera_failure(self, room: str, camera_info: CameraInfo, 
                              was_online: bool, reason: str):
        """Обрабатывает неудачную проверку камеры"""
        status = self.camera_manager.camera_status[room]
        status.fail_count += 1
        status.last_check = time.time()
        
        # Отправляем алерт только при превышении порога ошибок
        if (status.fail_count >= self.config.camera_fail_threshold and was_online):
            status.is_online = False
            message = f"{camera_info.description} недоступна! {reason}"
            self._send_message(message)
            self.logger.warning(message)
    
    def _arp_update_loop(self):
        """Фоновое обновление ARP кэша"""
        while not self.stop_event.is_set():
            try:
                self.arp_cache.update_cache()
            except Exception as e:
                self.logger.error(f"Ошибка при обновлении ARP кэша: {e}")
            
            self.stop_event.wait(self.config.arp_cache_update_interval)
    
    def _send_message(self, message: str):
        """Отправляет сообщение через колбэк"""
        if self.message_callback:
            try:
                asyncio.create_task(self.message_callback(message))
            except Exception as e:
                self.logger.error(f"Ошибка при отправке сообщения: {e}")
    
    def get_status_report(self) -> str:
        """Возвращает отчет о статусе камер"""
        if not self.camera_manager.cameras:
            return "Камеры не загружены"
        
        online_cameras = []
        offline_cameras = []
        
        for room, camera_info in self.camera_manager.cameras.items():
            status = self.camera_manager.camera_status[room]
            if status.is_online:
                online_cameras.append(camera_info.description)
            else:
                offline_cameras.append(
                    f"{camera_info.description} (ошибок: {status.fail_count})"
                )
        
        report = f"Мониторинг {'активен' if not self.stop_event.is_set() else 'остановлен'}\n"
        report += f"Всего камер: {len(self.camera_manager.cameras)}\n"
        report += f"Онлайн: {len(online_cameras)}\n"
        report += f"Оффлайн: {len(offline_cameras)}\n"
        
        if offline_cameras:
            report += "\nНеработающие камеры:\n" + "\n".join(offline_cameras)
        
        return report

# --- Telegram бот ---
class TelegramBot:
    """Асинхронный Telegram бот на aiogram"""
    
    def __init__(self, config: Config, monitor: CameraMonitor, logger: logging.Logger):
        self.config = config
        self.monitor = monitor
        self.logger = logger
        
        # Инициализация бота и диспетчера
        self.bot = Bot(
            token=config.telegram_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.dp = Dispatcher()
        self.router = Router()
        
        # Регистрация обработчиков
        self._register_handlers()
        self.dp.include_router(self.router)
        
        # Установка колбэка для отправки сообщений
        self.monitor.set_message_callback(self.send_message)
    
    def _register_handlers(self):
        """Регистрирует обработчики команд"""
        
        @self.router.message(F.text == "/start")
        async def handle_start(message: Message):
            self.logger.info(f"Команда /start от пользователя {message.from_user.id}")
            if self.monitor.start_monitoring():
                await message.answer("Мониторинг камер запущен.")
            else:
                await message.answer("Ошибка при запуске мониторинга.")
        
        @self.router.message(F.text == "/stop")
        async def handle_stop(message: Message):
            self.logger.info(f"Команда /stop от пользователя {message.from_user.id}")
            self.monitor.stop_monitoring()
            await message.answer("Мониторинг камер остановлен.")
        
        @self.router.message(F.text == "/status")
        async def handle_status(message: Message):
            self.logger.info(f"Команда /status от пользователя {message.from_user.id}")
            status_report = self.monitor.get_status_report()
            await message.answer(status_report)
        
        @self.router.message(F.text == "/refresharp")
        async def handle_refresh_arp(message: Message):
            self.logger.info(f"Команда /refresharp от пользователя {message.from_user.id}")
            if self.monitor.arp_cache.update_cache():
                await message.answer("ARP кэш успешно обновлён.")
            else:
                await message.answer("Ошибка при обновлении ARP кэша.")
        
        @self.router.message(F.text == "/getlogs")
        async def handle_get_logs(message: Message):
            self.logger.info(f"Команда /getlogs от пользователя {message.from_user.id}")
            try:
                log_path = Path(self.config.log_file)
                if log_path.exists():
                    from aiogram.types import FSInputFile
                    log_file = FSInputFile(log_path)
                    await message.answer_document(log_file)
                else:
                    await message.answer("Файл логов не найден.")
            except Exception as e:
                self.logger.error(f"Ошибка при отправке логов: {e}")
                await message.answer("Ошибка при отправке файла логов.")
    
    async def send_message(self, text: str):
        """Отправляет сообщение в чат"""
        try:
            await self.bot.send_message(chat_id=self.config.chat_id, text=text)
            self.logger.debug(f"Сообщение отправлено: {text}")
        except Exception as e:
            self.logger.error(f"Ошибка при отправке сообщения: {e}")
    
    async def start_polling(self):
        """Запускает поллинг бота"""
        try:
            await self.send_message("Бот запущен!")
            self.logger.info("Начало поллинга бота")
            await self.dp.start_polling(self.bot)
        except Exception as e:
            self.logger.error(f"Ошибка при работе бота: {e}")
            raise
        finally:
            await self.bot.session.close()

# --- Главная функция ---
async def main():
    """Главная функция приложения"""
    try:
        # Загрузка и валидация конфигурации
        config = Config.from_env()
        
        # Настройка логирования
        logger = setup_logging(config.log_file)
        logger.info("=" * 50)
        logger.info("Запуск приложения мониторинга камер")
        
        # Инициализация компонентов
        arp_cache = ARPCache(config, logger)
        camera_manager = CameraManager(config, arp_cache, logger)
        monitor = CameraMonitor(config, camera_manager, arp_cache, logger)
        
        # Инициализация и запуск бота
        bot = TelegramBot(config, monitor, logger)
        
        logger.info("Все компоненты инициализированы")
        await bot.start_polling()
        
    except EnvironmentError as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА - Неверная конфигурация: {e}")
        exit(1)
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА при запуске: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
