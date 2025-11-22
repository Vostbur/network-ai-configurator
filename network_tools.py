import asyncio
import asyncssh
from typing import List, Dict, Any, Optional
from app.models import EquipmentType # Импортируем тип оборудования


class SSHClient:
    """
    Клиент для SSH подключения к сетевому оборудованию.
    
    Поддерживает различные типы оборудования и обрабатывает
    их специфические особенности (приглашения, режимы и т.д.).
    """
    
    def __init__(
        self,
        host: str,
        username: str,
        password: Optional[str] = None,
        key_filename: Optional[str] = None,
        port: int = 22,
        timeout: int = 30
    ):
        """
        Инициализация SSH клиента.
        
        Args:
            host: IP адрес или хостнейм устройства
            username: Имя пользователя
            password: Пароль (если используется аутентификация по паролю)
            key_filename: Путь к приватному ключу (если используется ключ)
            port: SSH порт (по умолчанию 22)
            timeout: Таймаут подключения в секундах
        """
        self.host = host
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.port = port
        self.timeout = timeout
        self.connection: Optional[asyncssh.SSHClientConnection] = None
        self.stdin: Optional[asyncssh.SSHWriter] = None
        self.stdout: Optional[asyncssh.SSHReader] = None
        self.stderr: Optional[asyncssh.SSHReader] = None
        
    async def connect(self) -> bool:
        """
        Установка SSH соединения.
        
        Returns:
            True если подключение успешно, False в противном случае
        """
        try:
            connect_kwargs = {
                'host': self.host,
                'port': self.port,
                'username': self.username,
                'known_hosts': None,
                'connect_timeout': self.timeout
            }
            
            if self.password:
                connect_kwargs['password'] = self.password
            elif self.key_filename:
                connect_kwargs['client_keys'] = [self.key_filename]
            else:
                raise ValueError("Необходимо указать password или key_filename")
            
            self.connection = await asyncssh.connect(**connect_kwargs)
            
            # Создаем интерактивную оболочку
            self.stdin, self.stdout, self.stderr = await self.connection.open_session(
                term_type='vt100',
                term_size=(200, 50)
            )
            
            # Ждем начального приглашения
            await asyncio.sleep(2)
            initial_output = await self._read_until_timeout(3.0)
            print(f"[SSHClient] Initial output from {self.host}: {repr(initial_output)}")
            
            return True
            
        except Exception as e:
            print(f"[SSHClient] Ошибка подключения к {self.host}: {e}")
            return False
    
    async def disconnect(self):
        """Закрытие SSH соединения."""
        if self.stdin:
            self.stdin.close()
        if self.connection:
            self.connection.close()
            await self.connection.wait_closed()
        self.connection = None
        self.stdin = None
        self.stdout = None
        self.stderr = None
    
    async def _read_until_timeout(self, timeout: float = 5.0) -> str:
        """Чтение вывода с таймаутом."""
        if not self.stdout:
            return ""
            
        output = ""
        try:
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    # Читаем данные (уже декодированные в строку)
                    chunk = await asyncio.wait_for(self.stdout.read(1024), timeout=0.5)
                    if chunk:
                        output += chunk
                        # print(f"Received: {repr(chunk)}")  # Для отладки
                        
                        # Если получили приглашение, выходим
                        # Используем более точные приглашения, специфичные для Cisco IOS
                        # Например, 'Router>', 'Router#', 'Router(config)#'
                        if '#' in output or '>' in output or '$' in output or ':' in output:
                            break
                except asyncio.TimeoutError:
                    # Если нет данных, проверяем не пришло ли приглашение
                    if '#' in output or '>' in output or '$' in output or ':' in output:
                        break
                    continue
                    
        except Exception as e:
            print(f"[SSHClient] Ошибка чтения: {e}")
            
        return output
    
    async def send_command(
        self,
        command: str,
        wait_for_prompt: bool = True,
        timeout: float = 10.0
    ) -> str:
        """
        Отправка команды и чтение вывода.
        
        Args:
            command: Команда для выполнения
            wait_for_prompt: Ждать ли приглашения
            timeout: Таймаут выполнения команды
            
        Returns:
            Вывод команды
        """
        if not self.stdin or not self.stdout:
            raise Exception("Нет активного подключения")
        
        print(f"[SSHClient] Sending command: {command}")  # Для отладки
        
        # Очищаем буфер перед отправкой команды
        await asyncio.sleep(0.5)
        
        # Отправляем команду
        self.stdin.write(command + '\r\n')  # Используем \r\n для сетевого оборудования
        await self.stdin.drain()
        
        # Читаем вывод
        output = await self._read_until_timeout(timeout)
        
        print(f"[SSHClient] Received output for '{command}': {repr(output)}") # Для отладки
        return output
    
    async def execute_command(
        self,
        command: str,
        timeout: float = 10.0
    ) -> Dict[str, Any]:
        """
        Выполнение одной команды на устройстве.
        
        Args:
            command: Команда для выполнения
            timeout: Таймаут выполнения команды
            
        Returns:
            Словарь с результатами выполнения
        """
        try:
            output = await self.send_command(command, timeout=timeout)
            
            # Проверяем успешность выполнения по наличию ошибок в выводе
            success = not any(error in output.lower() for error in ['error', 'invalid', 'failed', 'incorrect', '%'])
            
            return {
                "success": success,
                "command": command,
                "output": output,
                "error": None if success else "Обнаружена ошибка в выводе команды"
            }
            
        except asyncio.TimeoutError:
            return {
                "success": False,
                "command": command,
                "output": "",
                "error": f"Таймаут выполнения команды ({timeout}с)"
            }
        except Exception as e:
            return {
                "success": False,
                "command": command,
                "output": "",
                "error": str(e)
            }
    
    async def execute_commands(
        self,
        commands: List[str],
        equipment_type: EquipmentType,
        delay_between_commands: float = 1.0
    ) -> Dict[str, Any]:
        """
        Выполнение списка команд с учетом специфики оборудования.
        
        Args:
            commands: Список команд для выполнения
            equipment_type: Тип оборудования
            delay_between_commands: Задержка между командами в секундах
            
        Returns:
            Словарь с результатами выполнения всех команд
        """
        results = []
        all_success = True
        
        try:
            # Специфичные для оборудования команды для входа в режим конфигурации
            config_mode_commands = self._get_config_mode_commands(equipment_type)
            
            print(f"[SSHClient] Executing config mode commands: {config_mode_commands}")
            # Выполняем команды входа в режим конфигурации
            for cmd in config_mode_commands:
                result = await self.execute_command(cmd)
                results.append(result)
                if not result["success"]:
                    print(f"[SSHClient] Failed to enter config mode with command '{cmd}'. Stopping.")
                    all_success = False
                    break # Прерываем, если не удалось войти в режим конфигурации
                await asyncio.sleep(delay_between_commands)
            
            if all_success:
                # --- НОВАЯ ЛОГИКА: Удаляем команды режима конфигурации из основного списка ---
                main_commands = [cmd for cmd in commands if cmd not in config_mode_commands]
                print(f"[SSHClient] Executing main commands (filtered): {main_commands}")
                # Выполняем основные команды
                for cmd in main_commands:
                    result = await self.execute_command(cmd)
                    results.append(result)
                    if not result["success"]:
                        all_success = False
                    await asyncio.sleep(delay_between_commands)
            
            # Команды выхода из режима конфигурации
            exit_commands = self._get_exit_commands(equipment_type)
            print(f"[SSHClient] Executing exit commands: {exit_commands}")
            for cmd in exit_commands:
                result = await self.execute_command(cmd)
                results.append(result)
                await asyncio.sleep(delay_between_commands)
            
            return {
                "success": all_success,
                "equipment_type": equipment_type.value,
                "total_commands": len(commands),
                "successful_commands": sum(1 for r in results if r["success"]),
                "results": results
            }
            
        except Exception as e:
            print(f"[SSHClient] Exception in execute_commands: {e}")
            return {
                "success": False,
                "equipment_type": equipment_type.value,
                "total_commands": len(commands),
                "successful_commands": 0,
                "results": results,
                "error": str(e)
            }
    
    def _get_config_mode_commands(self, equipment_type: EquipmentType) -> List[str]:
        """
        Получение команд для входа в режим конфигурации.
        
        Args:
            equipment_type: Тип оборудования
            
        Returns:
            Список команд для входа в режим конфигурации
        """
        commands_map = {
            EquipmentType.CISCO_IOS: ["enable", "configure terminal"],
            EquipmentType.JUNIPER_JUNOS: ["configure"],
            EquipmentType.HUAWEI: ["system-view"],
            EquipmentType.MIKROTIK: []  # MikroTik не требует входа в режим конфигурации
        }
        return commands_map.get(equipment_type, [])
    
    def _get_exit_commands(self, equipment_type: EquipmentType) -> List[str]:
        """
        Получение команд для выхода из режима конфигурации.
        
        Args:
            equipment_type: Тип оборудования
            
        Returns:
            Список команд для выхода из режима конфигурации
        """
        commands_map = {
            EquipmentType.CISCO_IOS: ["end", "exit"],
            EquipmentType.JUNIPER_JUNOS: ["commit", "exit"],
            EquipmentType.HUAWEI: ["commit", "quit"],
            EquipmentType.MIKROTIK: []
        }
        return commands_map.get(equipment_type, [])


# --- Функция, которая будет вызываться из mcp_server ---
# Она теперь принимает тип оборудования в виде строки и преобразует его
async def execute_commands_ssh(commands: list, ip: str, username: str, password: str, device_type_str: str = "cisco_ios") -> str:
    """
    Асинхронно выполняет список команд на сетевом устройстве через SSH, используя SSHClient.
    """
    # Преобразуем строку типа устройства в enum
    try:
        device_type_enum = EquipmentType(device_type_str.lower())
    except ValueError:
        print(f"[NetworkTools] Неизвестный тип устройства: {device_type_str}. Использую 'cisco_ios' по умолчанию.")
        device_type_enum = EquipmentType.CISCO_IOS

    client = SSHClient(host=ip, username=username, password=password)

    if await client.connect():
        try:
            execution_result = await client.execute_commands(
                commands=commands,
                equipment_type=device_type_enum,
                delay_between_commands=1.0 # Можно сделать настраиваемым
            )
            
            # Возвращаем агрегированный вывод или ошибку
            if execution_result["success"]:
                # Собираем вывод успешных команд
                output_lines = [f"Command: {r['command']}\nOutput: {r['output']}\n" for r in execution_result["results"] if r["success"]]
                return "\n".join(output_lines)
            else:
                # Если хотя бы одна команда неуспешна, возвращаем ошибку
                error_results = [r for r in execution_result["results"] if not r["success"]]
                if error_results:
                    first_error = error_results[0]
                    return f"Ошибка выполнения команды '{first_error['command']}': {first_error['output'] or first_error['error']}"
                else:
                    return f"Ошибка выполнения команд: {execution_result.get('error', 'Неизвестная ошибка')}"
        
        finally:
            await client.disconnect()
    else:
        raise Exception(f"Не удалось подключиться к устройству {ip} под пользователем {username}.")
