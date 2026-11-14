# Установка sponsrdump

Рекомендуется установка при помощи [uv](https://docs.astral.sh/uv/), хотя можно обойтись и обычным `pip`.

## Из PyPI

Приложение устанавливается как изолированная утилита:

```bash
uv tool install sponsrdump
```

Обновление:

```bash
uv tool upgrade sponsrdump
```

или с помощью pip:

```bash
pip install sponsrdump
```

## Из исходников

Клонируем репозиторий и синхронизируем среду разработки:

```bash
git clone https://github.com/idlesign/sponsrdump sponsrdump
cd sponsrdump
uv sync
```

Команды в среде проекта запускаются через `uv run`.
