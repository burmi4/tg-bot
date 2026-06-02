# Telegram Bot — Парсер государственных тендеров (геодезия)

Бот автоматически мониторит два сайта белорусских госзакупок каждые 30 секунд и отправляет в Telegram уведомления о новых тендерах, связанных с геодезией. Пользователь может добавлять собственные ключевые слова и настраивать фильтры.

## Стек технологий

| Компонент | Технология |
|-----------|-----------|
| Telegram Bot | `aiogram 3.x` |
| Веб-скрапинг | `crawlee[playwright]` + `PlaywrightCrawler` |
| Антиблокировка | `cloakbrowser` (кастомный Chromium с патчами на уровне C++) |
| Периодические задачи | `apscheduler` (AsyncIOScheduler) |
| Хранение данных | `aiosqlite` (SQLite — хранение уже отправленных тендеров + пользовательских настроек) |
| Конфигурация | `.env` файл через `python-dotenv` |

## Архитектура

```
d:\coding\tg bot\
├── pyproject.toml           # UV project config + ruff + basedpyright
├── .env                     # BOT_TOKEN, CHAT_IDS
├── .env.example             # Шаблон .env
├── src/
│   └── tender_bot/
│       ├── __init__.py
│       ├── __main__.py      # Точка входа: запуск бота + планировщика
│       ├── config.py        # Загрузка .env, настройки
│       ├── db.py            # SQLite: init, CRUD для тендеров и пользовательских настроек
│       ├── models.py        # Pydantic-модели TenderItem, UserSettings
│       ├── bot/
│       │   ├── __init__.py
│       │   ├── handlers.py  # Команды бота: /start, /keywords, /filters, /status
│       │   └── keyboards.py # Inline-клавиатуры для управления фильтрами
│       └── scrapers/
│           ├── __init__.py
│           ├── base.py      # Базовый класс скрапера с CloakBrowser
│           ├── goszakupki.py # Парсер goszakupki.by
│           ├── icetrade.py  # Парсер icetrade.by
│           └── scheduler.py # APScheduler: запуск скрапинга каждые 30 сек
```

## Целевые сайты — результаты исследования

### 1. goszakupki.by (публичный доступ, без авторизации)

- **URL**: `https://goszakupki.by/tenders/posted`
- Поиск по ключевому слову: параметр `TendersSearch[text]=геодезия`
- **Селекторы**:
  - Поле поиска: `input#tenderssearch-text`
  - Строки тендеров: таблица с рядами, каждый содержит:
    - Номер (`aucXXXXXXXXXX`)
    - Заказчик
    - Название + ссылка (`a[href^="/tenders/view/"]` или `a[href^="/marketing/view/"]`)
    - Вид процедуры
    - Статус
    - Срок подачи
    - Стоимость (BYN)

### 2. icetrade.by (публичный доступ)

- **URL**: `https://icetrade.by/search/auctions`
- Поиск: параметр `search_text=геодезия`
- **Селекторы**:
  - Поле поиска: `input[name="search_text"]`
  - Результаты: ссылки вида `a[href*="/tenders/all/view/"]`
  - Каждый тендер — блок с:
    - Названием-ссылкой на `/tenders/all/view/XXXXXX`
    - Организацией
    - Номером
    - Датами

## Proposed Changes

### Инициализация проекта

#### [NEW] pyproject.toml
- UV-проект с зависимостями: `aiogram`, `crawlee[playwright]`, `cloakbrowser`, `apscheduler`, `aiosqlite`, `python-dotenv`, `pydantic`
- Настройки ruff и basedpyright

#### [NEW] .env.example
```
BOT_TOKEN=your_telegram_bot_token
DEFAULT_CHAT_ID=your_chat_id
DEFAULT_KEYWORDS=геодезия,геодезическ,межевание,кадастр,топограф
```

---

### Конфигурация и модели

#### [NEW] src/tender_bot/config.py
- Загрузка `BOT_TOKEN`, `DEFAULT_CHAT_ID`, `DEFAULT_KEYWORDS` из `.env`
- Dataclass `Settings` с валидацией

#### [NEW] src/tender_bot/models.py
- `TenderItem` (Pydantic): `source`, `tender_id`, `title`, `url`, `organization`, `price`, `deadline`, `status`, `found_at`
- `UserSettings`: `chat_id`, `keywords: list[str]`, `enabled: bool`

---

### База данных (SQLite)

#### [NEW] src/tender_bot/db.py
- `init_db()` — создание таблиц `seen_tenders`, `user_settings`
- `is_tender_seen(source, tender_id)` — проверка, отправляли ли мы уже этот тендер
- `mark_tender_seen(tender)` — сохранить тендер как отправленный
- `get_user_keywords(chat_id)` — получить ключевые слова пользователя
- `set_user_keywords(chat_id, keywords)` — обновить ключевые слова
- `get_all_subscribers()` — все подписчики

---

### Скраперы (Crawlee + CloakBrowser)

#### [NEW] src/tender_bot/scrapers/base.py
- `CloakBrowserPlugin` — кастомный `PlaywrightBrowserPlugin`, использующий бинарник CloakBrowser
- `create_stealth_crawler()` — фабрика `PlaywrightCrawler` с отключённым fingerprinting

#### [NEW] src/tender_bot/scrapers/goszakupki.py
- `scrape_goszakupki(keywords: list[str]) -> list[TenderItem]`
- Формирует URL с `TendersSearch[text]=keyword`
- Парсит таблицу тендеров через Playwright `page.query_selector_all()`
- Извлекает: номер, название, ссылку, заказчика, цену, дедлайн, статус

#### [NEW] src/tender_bot/scrapers/icetrade.py
- `scrape_icetrade(keywords: list[str]) -> list[TenderItem]`
- Формирует URL с `search_text=keyword`
- Парсит список тендеров через Playwright
- Извлекает: номер, название, ссылку, организацию, даты

#### [NEW] src/tender_bot/scrapers/scheduler.py
- `start_scheduler(bot, dp)` — запуск `AsyncIOScheduler` с интервалом 30 секунд
- Функция `poll_tenders()`:
  1. Получает список подписчиков из БД
  2. Для каждого подписчика собирает его ключевые слова
  3. Запускает оба скрапера параллельно (`asyncio.gather`)
  4. Фильтрует уже виденные тендеры через БД
  5. Форматирует и отправляет новые тендеры в Telegram

---

### Telegram Bot (aiogram 3)

#### [NEW] src/tender_bot/bot/handlers.py
- `/start` — регистрация пользователя, приветствие, дефолтные ключевые слова
- `/keywords` — показать текущие ключевые слова
- `/add <слово>` — добавить ключевое слово для поиска
- `/remove <слово>` — удалить ключевое слово
- `/filters` — показать доступные фильтры (регион, тип процедуры, статус)
- `/status` — показать статус бота (последний скан, кол-во найденных тендеров)
- `/stop` — приостановить уведомления
- `/resume` — возобновить уведомления

#### [NEW] src/tender_bot/bot/keyboards.py
- Inline-клавиатуры для:
  - Управления ключевыми словами (добавить/удалить)
  - Выбора региона (Минск, Брест, Гомель, и т.д.)
  - Типа закупки

---

### Точка входа

#### [NEW] src/tender_bot/__main__.py
- Инициализация БД
- Создание `Bot` и `Dispatcher`
- Регистрация хендлеров
- Запуск планировщика
- `dp.start_polling(bot)`

---

## User Review Required

> [!IMPORTANT]
> **Токен бота**: Вам нужно создать бота через [@BotFather](https://t.me/BotFather) в Telegram и получить токен. Он будет записан в `.env` файл.

> [!IMPORTANT]
> **Chat ID**: Нужен ID чата/группы, куда бот будет отправлять тендеры. Его можно получить через `/start` команду — бот автоматически запишет ваш `chat_id`.

> [!WARNING]
> **CloakBrowser**: Пакет `cloakbrowser` при первом запуске скачает специальный бинарник Chromium (~200 MB). Убедитесь, что есть стабильное интернет-соединение.

> [!WARNING]
> **Интервал 30 секунд**: Очень агрессивный интервал для скрапинга. Рекомендуется начать с 2-5 минут, чтобы не получить IP-бан. Оба сайта — государственные, и могут блокировать частые запросы. Если вы уверены в 30 секундах, я реализую именно так.

## Open Questions

1. **Интервал опроса**: 30 секунд — это действительно нужный интервал? При двух сайтах это означает ~120 запросов/час. Рекомендую 2-5 минут.
2. **Дефолтные ключевые слова**: Помимо «геодезия», какие ещё слова искать по умолчанию? Предлагаю: `геодезия, геодезическ, межевание, кадастр, топограф, землеустро`.
3. **Формат сообщения в Telegram**: Какой формат предпочтителен? Предлагаю:
   ```
   🔔 Новый тендер (goszakupki.by)
   
   📋 Строительно-геодезические изыскания...
   🏢 ОАО «Строительная компания»
   💰 15 000 BYN
   📅 Дедлайн: 05.06.2026
   🔗 Ссылка на тендер
   ```
4. **Многопользовательский режим**: Бот будет для одного пользователя или нескольких? Сейчас запланирован многопользовательский режим (каждый может настроить свои ключевые слова).

## Verification Plan

### Automated Tests
- `uv run ruff check --fix .` — линтинг
- `uv run basedpyright` — строгая проверка типов
- Ручной запуск бота: `uv run python -m tender_bot`

### Manual Verification
- Отправка `/start` боту → проверка регистрации
- Отправка `/add геодезия` → проверка добавления ключевого слова
- Ожидание 30 сек → проверка получения уведомлений о тендерах
- Проверка что дубли не отправляются повторно
