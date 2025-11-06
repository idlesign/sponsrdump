# sponsrdump

<https://github.com/idlesign/sponsrdump>

[![PyPI - Version](https://img.shields.io/pypi/v/sponsrdump)](https://pypi.python.org/pypi/sponsrdump)
[![License](https://img.shields.io/pypi/l/sponsrdump)](https://pypi.python.org/pypi/sponsrdump)
[![Coverage](https://img.shields.io/coverallsCoverage/github/idlesign/sponsrdump)](https://coveralls.io/r/idlesign/sponsrdump)

## Описание

*Приложение позволяет получить локальные копии материалов, на которые у вас уже имеется подписка, с сайта sponsr.ru.*

Умеет скачивать тексты (статьи), аудио (подкаст), видео.


## Зависимости

* Unix
* Python 3.11+
* ffmpeg (``sudo apt install ffmpeg``)
* uv (для установки и обновления приложения)


## Установка и обновление

Производится при помощи приложения [uv](https://docs.astral.sh/uv/getting-started/installation/):

```shell
$ uv tool install sponsrdump
```

После этого запускать приложение можно командой

```shell
$ sponsrdump
```

Для обновления выполните

```shell
$ uv tool upgrade sponsrdump
```


## Начало работы

1. Перейдите в браузере на страницу нужного проекта.
   Для примера используем проект "Уроки истории" - <https://sponsr.ru/uzhukoffa_lessons/>
2. Если вы ещё не авторизовались на сайте (не вошли), сделайте это.
3. Удостоверьтесь, что материалы данного проекта вам доступны. Если нет, оформите подписку на нужный проект.
4. Теперь нам потребуется получить значение cookie ``SESS`` для сайта sponsr.ru, чтобы приложение могло собрать нужные материалы.
   Один из вариант получения значения куки:

   1. В браузере нажмите F12, откроется панель разработчика, открываем вкладку Сеть.
   2. Переходим на страницу попроще (где меньше обращений к ресурсам, чтобы не запутаться), например, <https://sponsr.ru/img/new/white-logo.svg>
   3. На вкладке Сеть выделяем строку с текстом white-logo.svg. В открывшейся панели ищем раздел Заголовки запроса.
      Находим пункт Cookie и копируем из него текст, начиная с ``SESS=`` и до первой же точки с запятой.
      Этот текст — пропуск на сайт для нашего собирателя.
5. Создаём текстовый файл с названием ``sponsrdump_auth.txt`` в удобной директории (из которой мы будем запускать приложение).
6. Скопированное ранее значение cookie ``SESS`` помещаем в файл из п.5, сохраняем.


В ходе сбора материалов в директории, из которой запущено приложение, будет создан файл ``sponsrdump.json``,
с информацией о том, что уже было успешно собрано. Таким образом, при следующем запуске приложения будут собраны только новые материалы.


## Примеры запуска

### Из командной строки

В примере мы используем фильтр, который инструктирует собирателя на поиск тех статей, в заголовке которых есть слово ``Урок ``.

Мы будем собирать все файлы (тексты, аудио, видео), начиная от старых к новым, и складывать их в поддиректорию ``here/`` текущей директории.

Для видео будем предпочитать разрешение ``640x360``. Сделаем видео с текстом статьи — ``--text-to-video``.


```shell
$ sponsrdump "https://sponsr.ru/uzhukoffa_lessons/" --title "Урок " --to here/ --prefer-video 640x360 --text-to-video
```

### Из кода

В примере ниже использованы все те же настройки, что и в примере запуска из командной строки (выше).

```python
dumper = SponsrDumper('https://sponsr.ru/uzhukoffa_lessons/')
dumper.search(func_filter=lambda post_info: 'Урок ' in post_info['post_title'])
dumper.dump('here/', prefer_video=VideoPreference(frame='640x360'), text_to_video=True)
```

### В контейнере

Будет полезно для тех, кто хочет выгружать видео сразу на свой домашний NAS.

Требует наличия в системе ``Docker``. Если у вас есть ``make``: 

```shell
$ make run
$ uvx sponsrdump "https://sponsr.ru/uzhukoffa_lessons/" --title "Урок 309" --prefer-video 640x360
```

Можно и без ``make`` и ``shell``, в данном примере монтируем auth и json файлы и каталог ``dump``, чтобы сохранять данные вне контейнера:

```shell
$ docker build -t sponsrdump .
$ docker run -it -v $(pwd)/sponsrdump_auth.txt:/sponsrdump_auth.txt -v $(pwd)/sponsrdump.json:/sponsrdump.json -v $(pwd)/dump:/dump sponsrdump uvx sponsrdump "https://sponsr.ru/uzhukoffa_lessons/" --title "Урок 309" --prefer-video 640x360
```

## Для разработки

При разработке используется [makeapp](https://pypi.org/project/makeapp/). Ставим:

```shell
$ uv tool install makeapp
```

После клонирования репозитория sponsrdump, в его директории выполняем:

```shell
# ставим утилиты
$ ma tools

# инициализируем виртуальное окружение
$ ma up --tool

# теперь в окружении доступны зависимости и команда sponsrdump
```

Проверь стиль перед отправкой кода на обзор:

```shell
# проверяем стиль
$ ma style
```
