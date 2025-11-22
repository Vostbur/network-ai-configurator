import os
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import ollama
import re
from app.models import EquipmentType

# Импортируем инструменты
from tools import NetworkDocumentationTool, ConfigurationValidator

app = FastAPI()

# --- Общий список ключевых слов для настройки ---
CONFIG_KEYWORDS = [
    "настроить", "конфигурация", "команда", "устройство", "интерфейс", "interface",
    "ip адрес", "router", "маршрутизатор", "hostname", "хост", "изменить", "change", 
    "set", "configure", "apply", "включить", "отключить", "shutdown", "no shutdown"
]

# --- Создаём и инициализируем инструмент документации ---
# Это должно быть выполнено один раз при запуске сервера
doc_tool = NetworkDocumentationTool(data_path="data/documentation")

# --- Pydantic модели ---
class RAGRequest(BaseModel):
    query: str
    device_type: str

class ExecuteRequest(BaseModel):
    commands: List[str]
    device_ip: str
    username: str
    password: str
    device_type: str

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    device_type: Optional[str] = None
    device_ip: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

# --- Инструменты ---
@app.post("/tools/rag")
async def rag_tool(request: RAGRequest):
    print(f"[LOG TOOL RAG] Вызов RAG с query: '{request.query}', device_type: '{request.device_type}'")
    
    # Преобразуем строку типа устройства в enum
    try:
        device_type_enum = EquipmentType(request.device_type.lower())
    except ValueError:
        print(f"[LOG TOOL RAG] Неизвестный тип устройства: {request.device_type}. Использую 'cisco_ios' по умолчанию.")
        device_type_enum = EquipmentType.CISCO_IOS

    # Выполняем поиск команд с помощью нового инструмента
    results = await doc_tool.search_commands(request.query, device_type_enum, k=5)
    print(f"[LOG TOOL RAG] Результаты RAG: {results}")
    return {"results": results}

@app.post("/tools/execute")
async def execute_tool(request: ExecuteRequest):
    print(f"[LOG TOOL EXECUTE] Вызов EXECUTE с командами: {request.commands}, на устройстве {request.device_ip}, тип: {request.device_type}")
    
    # Преобразуем строку типа устройства в enum
    try:
        device_type_enum = EquipmentType(request.device_type.lower())
    except ValueError:
        print(f"[LOG TOOL EXECUTE] Неизвестный тип устройства: {request.device_type}. Использую 'cisco_ios' по умолчанию.")
        device_type_enum = EquipmentType.CISCO_IOS

    from network_tools import execute_commands_ssh
    try:
        # Передаём device_type_str в execute_commands_ssh
        output = await execute_commands_ssh(request.commands, request.device_ip, request.username, request.password, request.device_type)
        print(f"[LOG TOOL EXECUTE] Результат выполнения: {repr(output)}")
        
        # Проверка на ошибки
        if '%' in output or 'error' in output.lower():
             print(f"[LOG TOOL EXECUTE] Обнаружена ошибка в выводе: {output}")
             return {"output": f"Ошибка выполнения команды: {output}", "error": True}
        
        return {"output": output, "error": False}
    except Exception as e:
        print(f"[LOG TOOL EXECUTE] Ошибка выполнения: {str(e)}")
        return {"output": f"Ошибка подключения или выполнения: {str(e)}", "error": True}

# --- Основной эндпоинт чата ---
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    print(f"[LOG SERVER] Получен запрос: device_type={request.device_type}, device_ip={request.device_ip}, username={'***' if request.username else 'None'}, password={'***' if request.password else 'None'}, messages={request.messages}")
    
    model_name = os.getenv('OLLAMA_MODEL', 'mistral')

    user_query = request.messages[-1]["content"] if request.messages else ""
    print(f"[LOG SERVER] Анализируется запрос пользователя: '{user_query}'")
    
    user_query_lower = user_query.lower()
    needs_config_action = any(keyword in user_query_lower for keyword in CONFIG_KEYWORDS)
    print(f"[LOG SERVER] Нужна ли настройка (needs_config_action): {needs_config_action}, проверено по ключевям словам: {CONFIG_KEYWORDS}")

    if needs_config_action:
        print(f"[LOG SERVER] Обнаружено действие по настройке.")
        if not request.device_type:
            print("[LOG SERVER] device_type отсутствует.")
            return {"response": "Неизвестен тип сетевого устройства. Пожалуйста, укажите тип (например, Cisco IOS, Juniper JunOS)."}

        print(f"[LOG SERVER] Выполняю поиск команд для запроса: '{user_query}' на устройстве типа {request.device_type}")
        rag_request = RAGRequest(query=user_query, device_type=request.device_type)
        rag_results = await rag_tool(rag_request)
        
        if not rag_results["results"]:
             print(f"[LOG SERVER] Не найдено команд для запроса: '{user_query}'")
             return {"response": f"Не найдено подходящих команд в документации для запроса: '{user_query}' на устройстве типа {request.device_type}."}

        # --- НОВАЯ ЛОГИКА: Фильтрация результатов RAG ---
        rag_results_list = rag_results["results"]
        print(f"[LOG SERVER] Найденные команды из RAG: {rag_results_list}")

        # Определим ключевое слово из запроса пользователя
        primary_cmd_keyword = None
        if "hostname" in user_query_lower or "имя хоста" in user_query_lower:
            primary_cmd_keyword = "hostname"
        elif "interface" in user_query_lower or "интерфейс" in user_query_lower:
            primary_cmd_keyword = "interface"
        elif "ip address" in user_query_lower or "ip адрес" in user_query_lower:
            primary_cmd_keyword = "ip address"
        # ... можно добавить другие

        filtered_commands = []
        if primary_cmd_keyword:
            # Попробуем найти строки, содержащие ключевое слово
            filtered_commands = [cmd_str for cmd_str in rag_results_list if primary_cmd_keyword in cmd_str.lower()]
            if filtered_commands:
                print(f"[LOG SERVER] Найдены команды, соответствующие ключевому слову '{primary_cmd_keyword}': {filtered_commands}")
                # Берём только отфильтрованные команды
                rag_results_list = filtered_commands
            else:
                print(f"[LOG SERVER] Команды, соответствующие ключевому слову '{primary_cmd_keyword}', не найдены. Используем все результаты RAG.")

        # --- Обработка команд ---
        # Здесь можно добавить логику извлечения команд из строк RAG
        # и подстановки значений из запроса, если они представлены как шаблоны
        processed_commands = []
        for cmd_str in rag_results_list: # Используем отфильтрованный или оригинальный список
            # Пример простой обработки: если в строке RAG есть <new_name> и в запросе есть имя
            if "hostname" in cmd_str and "<new_name>" in cmd_str:
                match = re.search(r'на\s+(\w+)(?:\s|$)', user_query, re.IGNORECASE)
                if match:
                    new_name = match.group(1)
                    cmd_str = cmd_str.replace("<new_name>", new_name)
            # Убираем placeholder-ы типа <...> в других командах для примера
            processed_cmd = re.sub(r'<[^>]+>', '', cmd_str).strip()
            if processed_cmd:
                # Извлекаем только саму команду из строки документации
                # Например, "hostname <new_name> - изменить имя хоста" -> "hostname <new_name>"
                # Ищем часть до первого '-' (если оно есть и не в середине слова/адреса)
                parts = processed_cmd.split(' - ', 1) # Разбиваем по первому вхождению ' - '
                command_part = parts[0].strip()
                if command_part: # Проверяем, что команда не пустая
                    processed_commands.append(command_part)
        
        suggested_commands = processed_commands
        print(f"[LOG SERVER] Обработанные команды: {suggested_commands}")
        
        if not suggested_commands:
            print("[LOG SERVER] Команды найдены в документации, но не извлечены/обработаны.")
            return {"response": f"Найдены документы, но команды не извлечены или требуют уточнения. Проверьте формат файла документации для {request.device_type}."}

        # --- Валидация команд ---
        print(f"[LOG SERVER] Проверяю команды на безопасность: {suggested_commands}")
        try:
            device_type_enum = EquipmentType(request.device_type.lower())
        except ValueError:
            device_type_enum = EquipmentType.CISCO_IOS # По умолчанию

        validation_result = ConfigurationValidator.validate_commands(suggested_commands, device_type_enum)
        if not validation_result["is_safe"]:
            warnings_str = "\n".join(validation_result["warnings"])
            print(f"[LOG SERVER] Обнаружены потенциально опасные команды: {warnings_str}")
            warning_context = f"\nПРЕДУПРЕЖДЕНИЕ: Были обнаружены потенциально опасные команды:\n{warnings_str}\nПожалуйста, убедитесь, что вы хотите выполнить их."
        else:
            warning_context = ""

        print(f"[LOG SERVER] Найденные команды: {suggested_commands}")

        if not request.device_ip or not request.username or not request.password:
            print("[LOG SERVER] Данные подключения отсутствуют.")
            commands_str = "\n".join(suggested_commands)
            return {"response": f"Найдены команды для выполнения:\n{commands_str}\n\nОднако, для их применения на устройстве необходимы данные подключения (IP, логин, пароль)."}
        
        print(f"[LOG SERVER] Пытаюсь выполнить команды на {request.device_ip}")
        exec_request = ExecuteRequest(
            commands=suggested_commands,
            device_ip=request.device_ip,
            username=request.username,
            password=request.password,
            device_type=request.device_type
        )
        exec_result = await execute_tool(exec_request)

        if exec_result.get("error"):
            print(f"[LOG SERVER] Ошибка при выполнении команд: {exec_result['output']}")
            return {"response": f"Ошибка при выполнения команд на устройстве: {exec_result['output']}"}

        context_for_model = f"""
        Пользователь хотел выполнить настройку: "{user_query}".
        Были найдены и применены следующие команды: {suggested_commands}.{warning_context}
        Результат выполнения команд на устройстве: {exec_result['output']}.
        Пожалуйста, сформулируй ответ для пользователя, подтверждая, что настройка была выполнена, и при необходимости поясни результат или предупреждения.
        """
        print(f"[LOG SERVER] Отправка контекста в модель для финального ответа.")
        final_response = ollama.chat(
            model=model_name,
            messages=[{"role": "user", "content": context_for_model}],
            options={"temperature": 0.1}
        )
        print("[LOG SERVER] Команды обработаны (с ошибкой или без), ответ сформирован.")
        return {"response": final_response['message']['content']}

    else:
        print(f"[LOG SERVER] Обычный запрос, передаю в модель. Query: {user_query}")
        response = ollama.chat(
            model=model_name,
            messages=request.messages,
            options={"temperature": 0.1}
        )
        return {"response": response['message']['content']}

# --- Инициализация при запуске сервера ---
@app.on_event('startup')
async def startup_event():
    print("[LOG SERVER] Инициализация инструментов документации...")
    await doc_tool.initialize()
    print("[LOG SERVER] Инструменты документации инициализированы.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)