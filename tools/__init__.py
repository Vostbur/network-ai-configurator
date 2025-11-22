"""
Инструменты для работы с документацией и валидации конфигураций.

Этот модуль содержит классы для:
- Поиска релевантной документации по типам оборудования
- Валидации сгенерированных команд на предмет безопасности
- Создания базовой документации для разных типов оборудования
"""

import aiofiles
import os
from typing import List, Dict, Any
from langchain_community.vectorstores import FAISS  # Импортируем FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from app.models import EquipmentType


class NetworkDocumentationTool:
    """
    Инструмент для работы с документацией сетевого оборудования.

    Использует векторный поиск для нахождения релевантных команд конфигурации
    на основе запроса пользователя и типа оборудования.
    """

    def __init__(self, data_path: str = "data/documentation"):
        """
        Инициализация инструмента документации.

        Args:
            data_path: Путь к директории с документацией
        """
        self.data_path = data_path
        # Используем модель для создания эмбеддингов текста
        # all-MiniLM-L6-v2 - хорошая и быстрая модель для английского и может работать с русским
        self.embeddings = HuggingFaceEmbeddings(
            model_name="mixedbread-ai/mxbai-embed-large-v1", # Указываем новую модель
            # model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},  # Укажите 'cuda', если доступен GPU
        )
        self.vector_stores = {}  # Словарь векторных баз для каждого типа оборудования

    async def initialize(self):
        """
        Инициализация векторных баз для каждого типа оборудования.

        Загружает документацию и создает векторные индексы для быстрого поиска.
        """
        for equipment_type in EquipmentType:
            docs = await self._load_documentation(equipment_type)
            if docs:
                print(
                    f"[NetworkDocumentationTool] Индексация документации для {equipment_type.value}..."
                )
                # Используем FAISS вместо Chroma
                self.vector_stores[equipment_type] = FAISS.from_documents(
                    documents=docs,
                    embedding=self.embeddings,
                )
                print(
                    f"[NetworkDocumentationTool] Индекс для {equipment_type.value} создан."
                )
            else:
                print(
                    f"[NetworkDocumentationTool] Нет документации для {equipment_type.value}"
                )

    async def _load_documentation(
        self, equipment_type: EquipmentType
    ) -> List[Document]:
        """
        Загрузка документации из файлов для конкретного типа оборудования.

        Args:
            equipment_type: Тип оборудования

        Returns:
            Список документов с командами конфигурации
        """
        docs = []
        docs_path = os.path.join(self.data_path, equipment_type.value)

        if not os.path.exists(docs_path):
            print(
                f"[NetworkDocumentationTool] Папка {docs_path} не найдена. Создаю базовую документацию."
            )
            # Создаем базовую документацию, если файлы отсутствуют
            docs = await self._create_basic_documentation(equipment_type)
            # Попробуем создать папку и файлы для будущего использования
            os.makedirs(docs_path, exist_ok=True)
            # Запишем базовую документацию в файлы
            basic_docs = self._get_basic_docs_dict()
            for filename, lines in basic_docs.get(equipment_type, {}).items():
                file_path = os.path.join(docs_path, filename)
                async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                    await f.write("\n".join(lines))
            return docs

        try:
            # Читаем все .txt файлы в директории
            for filename in os.listdir(docs_path):
                if filename.endswith(".txt"):
                    file_path = os.path.join(docs_path, filename)
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        content = await f.read()
                        # Разбиваем на строки, каждая строка - отдельный документ
                        # Это может быть гибко настроено (например, разбивать по абзацам или разделам)
                        lines = content.strip().split("\n")
                        for line in lines:
                            line = line.strip()
                            if line:  # Пропускаем пустые строки
                                docs.append(
                                    Document(
                                        page_content=line,
                                        metadata={
                                            "source": filename,
                                            "equipment": equipment_type.value,
                                        },
                                    )
                                )
        except Exception as e:
            print(f"Warning: Could not load documentation for {equipment_type}: {e}")

        return docs

    def _get_basic_docs_dict(self):
        """Вспомогательный метод для получения базовой документации."""
        return {
            EquipmentType.CISCO_IOS: {
                "general.txt": [
                    "enable - переход в привилегированный EXEC режим",
                    "configure terminal - вход в режим глобальной конфигурации",
                    "hostname <new_name> - изменить имя хоста маршрутизатора. Поменять имя хоста. Установить имя хоста.",
                    "show version - показать версию ПО",
                    "show running-config - показать текущую конфигурацию",
                    "copy running-config startup-config - сохранить конфигурацию",
                    "username <name> privilege <level> password <password> - создание пользователя",
                    "ip domain-name <domain> - настроить имя домена",
                    "ip name-server <ip-address> - настроить DNS сервер",
                    "service password-encryption - шифровать пароли в конфигурации",
                    "banner motd <banner_text> - настроить баннер сообщения дня",
                    "no ip domain-lookup - отключить DNS lookup для опечаток",
                ],
                "interface.txt": [
                    "interface <type> <number> - вход в режим конфигурации интерфейса",
                    "ip address <A.B.C.D> <A.B.C.D> - назначение IP-адреса интерфейсу",
                    "no shutdown - включение интерфейса",
                    "shutdown - отключение интерфейса",
                    "description <text> - добавить описание интерфейса",
                    "speed <speed> - настроить скорость интерфейса",
                    "duplex <full|half> - настроить дуплекс интерфейса",
                    "switchport mode access - настроить порт как access",
                    "switchport mode trunk - настроить порт как trunk",
                    "switchport access vlan <vlan-id> - назначить access порт в VLAN",
                    "switchport trunk allowed vlan <vlan-list> - разрешить VLAN на trunk",
                ],
                "routing.txt": [
                    "router ospf <process-id> - создание процесса OSPF",
                    "network <A.B.C.D> <wildcard-mask> area <area-id> - объявление сетей в OSPF",
                    "ip route <network> <mask> <next-hop> - статический маршрут",
                    "router bgp <as-number> - начать настройку BGP",
                    "neighbor <ip-address> remote-as <as-number> - настроить BGP соседа",
                    "redistribute <protocol> - redistribute маршрутов в протокол",
                ],
            },
            EquipmentType.JUNIPER_JUNOS: {
                "general.txt": [
                    "configure - вход в режим конфигурации",
                    "set system host-name <hostname> - изменить имя хоста",
                    "show version - показать версию ПО",
                    "show configuration | display set - показать конфигурацию в формате set",
                    "commit - применение изменений",
                    "rollback - откат изменений",
                    "exit - выход из режима конфигурации",
                    "request system reboot - перезагрузка системы",
                ],
                "interface.txt": [
                    "set interfaces <interface-name> unit 0 family inet address <ip/mask> - настроить IP на интерфейсе",
                    "set interfaces <interface-name> description <text> - добавить описание интерфейса",
                    "deactivate interfaces <interface-name> - отключить интерфейс",
                    "activate interfaces <interface-name> - включить интерфейс",
                    "set vlans <vlan-name> vlan-id <id> - создать VLAN",
                    "set interfaces <interface-name> unit 0 family ethernet-switching interface-mode access - настроить порт как access",
                    "set interfaces <interface-name> unit 0 family ethernet-switching vlan members <vlan-name> - назначить порт в VLAN",
                ],
                "routing.txt": [
                    "set protocols ospf area <area-id> interface <interface-name> - включить OSPF на интерфейсе",
                    "set routing-options static route <network> next-hop <gateway> - статический маршрут",
                    "set protocols bgp group <group-name> type external - начать настройку BGP",
                    "set protocols bgp group <group-name> peer-as <as-number> - настроить AS BGP соседа",
                ],
            },
            EquipmentType.HUAWEI: {
                "general.txt": [
                    "system-view - вход в системный вид",
                    "sysname <new_name> - изменить имя хоста",
                    "display version - показать версию ПО",
                    "display current-configuration - показать текущую конфигурацию",
                    "save - сохранить конфигурацию",
                    "user-interface vty 0 4 - настройка VTY линий",
                    "authentication-mode password - настройка аутентификации",
                    "quit - выход из текущего режима",
                    "return - возврат в пользовательский режим",
                ],
                "interface.txt": [
                    "interface <interface-type> <interface-number> - вход в режим интерфейса",
                    "ip address <ip-address> <mask> - настроить IP адрес",
                    "undo shutdown - включить интерфейс",
                    "shutdown - отключить интерфейс",
                    "description <text> - добавить описание интерфейса",
                    "port link-type access - настроить порт как access",
                    "port link-type trunk - настроить порт как trunk",
                    "port default vlan <vlan-id> - назначить access порт в VLAN",
                    "port trunk allow-pass vlan <vlan-list> - разрешить VLAN на trunk",
                ],
                "routing.txt": [
                    "ospf <process-id> - создать процесс OSPF",
                    "area <area-id> - создать область OSPF",
                    "network <network> <wildcard-mask> - объявить сеть в OSPF",
                    "ip route-static <network> <mask> <next-hop> - статический маршрут",
                    "bgp <as-number> - начать настройку BGP",
                    "peer <ip-address> as-number <as-number> - настроить BGP соседа",
                ],
            },
            EquipmentType.MIKROTIK: {
                "general.txt": [
                    "/system identity set name=<name> - изменить имя хоста",
                    "/system resource print - показать ресурсы",
                    "/system backup save name=<name> - создать бэкап",
                    "/system backup load name=<name> - загрузить бэкап",
                    "/system reboot - перезагрузка",
                    "/system shutdown - выключение",
                ],
                "interface.txt": [
                    "/interface bridge add name=<name> - создание bridge",
                    "/ip address add address=<ip/mask> interface=<interface> - добавить IP адрес",
                    "/interface enable <interface> - включить интерфейс",
                    "/interface disable <interface> - отключить интерфейс",
                    "/interface set <interface> name=<new_name> - переименовать интерфейс",
                    "/interface vlan add name=<name> interface=<parent> vlan-id=<id> - создать VLAN интерфейс",
                ],
                "routing.txt": [
                    "/ip route add dst-address=<network/mask> gateway=<gateway> - статический маршрут",
                    "/routing ospf instance add name=default router-id=<ip> - создать OSPF instance",
                    "/routing ospf interface add interfaces=<interface> - включить OSPF на интерфейсе",
                ],
            },
        }

    async def _create_basic_documentation(
        self, equipment_type: EquipmentType
    ) -> List[Document]:
        """
        Создание базовой документации для разных типов оборудования.

        Содержит основные команды конфигурации для каждого типа оборудования.
        """
        basic_docs_dict = self._get_basic_docs_dict()
        basic_docs = basic_docs_dict.get(equipment_type, {})

        docs = []
        for filename, lines in basic_docs.items():
            for line in lines:
                docs.append(
                    Document(
                        page_content=line,
                        metadata={
                            "source": f"basic_{filename}",
                            "equipment": equipment_type.value,
                        },
                    )
                )

        return docs

    async def search_commands(
        self, query: str, equipment_type: EquipmentType, k: int = 5
    ) -> List[str]:
        """
        Поиск релевантных команд в документации.

        Args:
            query: Поисковый запрос
            equipment_type: Тип оборудования
            k: Количество результатов

        Returns:
            Словарь с результатами поиска, включая команду и источник
        """
        if equipment_type not in self.vector_stores:
            print(
                f"[NetworkDocumentationTool] Векторный индекс для {equipment_type.value} не загружен."
            )
            return []

        # Используем FAISS для поиска
        # similarity_search возвращает Document объекты
        docs = self.vector_stores[equipment_type].similarity_search(query, k=k)
        # Возвращаем только текст команды
        return [doc.page_content for doc in docs]


class ConfigurationValidator:
    """
    Валидатор конфигурационных команд на предмет безопасности.

    Проверяет сгенерированные команды на наличие потенциально опасных операций
    и выдает предупреждения для команд, которые могут:
    - Вызвать простои сети
    - Повлиять на безопасность
    - Не иметь возможности отката
    """

    @staticmethod
    def validate_commands(
        commands: List[str], equipment_type: EquipmentType
    ) -> Dict[str, Any]:
        """
        Валидация сгенерированных команд.

        Args:
            commands: Список команд для проверки
            equipment_type: Тип оборудования

        Returns:
            Словарь с результатами валидации
        """
        warnings = []
        # Базовые паттерны, можно расширить для каждого EquipmentType
        dangerous_patterns = {
            EquipmentType.CISCO_IOS: [
                (r"\berase\b", "Стирание конфигурации (erase)"),
                (r"\bdelete\b", "Удаление файлов (delete)"),
                (r"\breload\b", "Перезагрузка оборудования (reload)"),
                (r"\bformat\b", "Форматирование (format)"),
                (r"\bwrite memory\b", "Сохранение конфигурации (write memory)"),
                (r"\bwrite\b", "Сохранение конфигурации (write)"),
                (r"\bno shutdown\b", "Включение интерфейса (no shutdown)"),
                (r"\bshutdown\b", "Отключение интерфейса (shutdown)"),
            ],
            EquipmentType.JUNIPER_JUNOS: [
                (r"\bcommit\b", "Применение изменений (commit)"),
                (
                    r"\brequest system reboot\b",
                    "Перезагрузка системы (request system reboot)",
                ),
                (
                    r"\brequest system halt\b",
                    "Выключение системы (request system halt)",
                ),
            ],
            EquipmentType.HUAWEI: [
                (r"\bsave\b", "Сохранение конфигурации (save)"),
                (r"\breset\b", "Сброс настроек (reset)"),
                (r"\breboot\b", "Перезагрузка (reboot)"),
                (r"\bshutdown\b", "Отключение интерфейса (shutdown)"),
            ],
            EquipmentType.MIKROTIK: [
                (r"/system reboot", "Перезагрузка (reboot)"),
                (r"/system shutdown", "Выключение (shutdown)"),
                (r"/interface disable", "Отключение интерфейса"),
            ],
        }

        current_patterns = dangerous_patterns.get(equipment_type, [])

        for cmd in commands:
            cmd_lower = cmd.lower()
            for pattern, description in current_patterns:
                if re.search(pattern, cmd_lower):
                    # Проверяем, что это не безопасная команда вроде "show running-config"
                    # Простая эвристика: если в команде есть 'show', 'display', 'get', 'view', 'print' - скорее всего безопасно
                    safe_keywords = ["show", "display", "get", "view", "print"]
                    if not any(safe in cmd_lower for safe in safe_keywords):
                        warnings.append(f"WARNING: {description}: {cmd}")

        return {
            "is_safe": len(warnings) == 0,
            "warnings": warnings,
            "dangerous_commands_count": len(warnings),
        }


# Необходимо для работы re.search
import re
