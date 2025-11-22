import asyncio
import aiohttp
import os
import re
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style
from colorama import init, Fore, Back, Style as ColoramaStyle

# Инициализация colorama для Windows
init(autoreset=True)

MCP_SERVER_URL = "http://localhost:8000"

# Глобальные переменные для хранения данных подключения
device_info = {
    "ip": None,
    "username": None,
    "password": None,
    "type": None
}

# Стиль для prompt_toolkit
style = Style.from_dict({
    'prompt': '#ansicyan bold',
    'help-text': '#ansiyellow',
})

# Комплитер для команд
command_completer = WordCompleter(['help', 'exit', 'quit', 'config'], ignore_case=True)

async def print_colored(text: str, color: str = Fore.WHITE):
    """Печатает текст с цветом."""
    print(color + text)

async def print_help():
    """Печатает справку."""
    await print_colored("\n--- Справка ---", Fore.CYAN)
    await print_colored("Доступные команды:", Fore.YELLOW)
    await print_colored("  help          - Показать эту справку", Fore.GREEN)
    await print_colored("  exit / quit   - Выйти из клиента", Fore.GREEN)
    await print_colored("  config        - Повторно ввести данные подключения", Fore.GREEN)
    await print_colored("\nПросто введите ваш запрос на естественном языке.", Fore.YELLOW)
    await print_colored("Например: 'поменяй имя хоста на cisco1'", Fore.YELLOW)
    await print_colored("Если данные подключения не указаны, клиент запросит их.", Fore.YELLOW)

async def get_user_input_async(session: PromptSession, prompt: str = ">>> "):
    """Асинхронное получение ввода от пользователя через prompt_toolkit."""
    return await session.prompt_async(prompt, completer=command_completer, style=style)

async def ensure_device_info(session: PromptSession): # <-- Принимает session
    """Запрашивает у пользователя недостающие данные подключения."""
    if not device_info["ip"]:
        device_info["ip"] = await get_user_input_async(session, f"{Fore.LIGHTBLUE_EX}Введите IP-адрес устройства: {ColoramaStyle.RESET_ALL}")
    if not device_info["username"]:
        device_info["username"] = await get_user_input_async(session, f"{Fore.LIGHTBLUE_EX}Введите имя пользователя: {ColoramaStyle.RESET_ALL}")
    if not device_info["password"]:
        device_info["password"] = await get_user_input_async(session, f"{Fore.LIGHTBLUE_EX}Введите пароль: {ColoramaStyle.RESET_ALL}")
    if not device_info["type"]:
        device_info["type"] = await get_user_input_async(session, f"{Fore.LIGHTBLUE_EX}Введите тип устройства (например, cisco_ios): {ColoramaStyle.RESET_ALL}")

async def chat_with_model(messages: list):
    """Отправляет сообщения на MCP-сервер и получает ответ."""
    try:
        # Подготовим словарь данных, исключив None
        payload = {
            "messages": messages,
        }
        # Добавляем только непустые поля
        if device_info["type"]:
            payload["device_type"] = device_info["type"]
        if device_info["ip"]:
            payload["device_ip"] = device_info["ip"]
        if device_info["username"]:
            payload["username"] = device_info["username"]
        if device_info["password"]:
            payload["password"] = device_info["password"]

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{MCP_SERVER_URL}/chat",
                json=payload
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("response", "Ответ не получен от модели.")
                else:
                    error_text = await resp.text()
                    return f"Ошибка от MCP-сервера: {resp.status} - {error_text}"
    except aiohttp.ClientError as e:
        return f"Ошибка подключения к MCP-серверу: {e}"
    except Exception as e:
        return f"Произошла ошибка: {e}"

async def main():
    await print_colored("Добро пожаловать в MCP-клиент для сетевой автоматизации!", Fore.LIGHTGREEN_EX)
    await print_colored("Введите 'help' для справки.", Fore.LIGHTYELLOW_EX)
    print("-" * 40)

    # Инициализируем историю команд
    session = PromptSession(history=FileHistory(os.path.expanduser('~/.network_client_history')))

    # Инициализируем историю сообщений
    messages = [
        {"role": "system", "content": f"Вы - помощник по настройке сетевого оборудования. Используйте инструменты для поиска и выполнения команд."}
    ]

    while True:
        try:
            user_input = await get_user_input_async(session)
        except (EOFError, KeyboardInterrupt): # Обработка Ctrl+D или Ctrl+C
            print("\nДо свидания!")
            break

        user_input_lower = user_input.lower().strip()

        if user_input_lower in ['exit', 'quit']:
            print("До свидания!")
            break
        elif user_input_lower == 'help':
            await print_help()
            continue
        elif user_input_lower == 'config':
            # Сбросим device_info, чтобы запросить снова
            device_info.update({"ip": None, "username": None, "password": None, "type": None})
            print("Данные подключения сброшены. Введите информацию снова при следующем запросе.")
            continue

        # Проверяем, нужно ли запросить информацию об устройстве ДО отправки
        needs_config = any(keyword in user_input_lower for keyword in [
            "настроить", "конфигурация", "команда", "устройство", "интерфейс", "interface",
            "ip адрес", "router", "маршрутизатор", "hostname", "хост", "изменить", "change",
            "set", "configure", "apply", "включить", "отключить", "shutdown", "no shutdown"
        ])

        if needs_config:
            print("Проверяю наличие данных подключения...")
            await ensure_device_info(session) # <-- Передаём session сюда
            # Обновляем системное сообщение с новой информацией
            messages[0]["content"] = f"Вы - помощник по настройке сетевого оборудования {device_info['type']}. Используйте инструменты для поиска и выполнения команд."

        # Добавляем сообщение пользователя в историю ПОСЛЕ проверки
        messages.append({"role": "user", "content": user_input})

        # Отправляем запрос на сервер
        bot_response = await chat_with_model(messages)

        # Выводим ответ модели с цветом
        await print_colored(f"Модель: {bot_response}", Fore.LIGHTMAGENTA_EX)

        # Добавляем ответ модели в историю
        messages.append({"role": "assistant", "content": bot_response})

if __name__ == "__main__":
    asyncio.run(main())