sponsrdump
==========
https://github.com/idlesign/sponsrdump

Описание
--------
*Приложение позволяет получить локальные копии материалов, на которые у вас уже имеется подписка, с сайта sponsr.ru.*

Умеет скачивать тексты (статьи), изображения, аудио (подкасты), видео. Поддерживает преобразование текстов в видео.

Зависимости
-----------
* Unix (Linux, macOS)
* Python 3.10+
* ffmpeg (``sudo apt install ffmpeg`` или ``brew install ffmpeg``)
* mp4decrypt (часть пакета Bento4, см. инструкции ниже)
* Python-пакеты: beautifulsoup4, html2text, lxml, requests, mpegdash, tqdm (``pip install -r requirements.txt``)

Установка mp4decrypt (Bento4)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``mp4decrypt`` — это утилита из пакета Bento4, необходимая для обработки видео. Установите её следующим образом:

**Linux**:

.. code-block:: sh

    sudo apt update
    sudo apt install git cmake make g++
    git clone https://github.com/axiomatic-systems/Bento4.git
    cd Bento4
    mkdir cmakebuild
    cd cmakebuild
    cmake -DCMAKE_BUILD_TYPE=Release ..
    make
    sudo cp mp4decrypt /usr/local/bin/

**macOS** (с использованием Homebrew):

.. code-block:: sh

    brew install bento4

После установки убедитесь, что ``mp4decrypt`` доступен:

.. code-block:: sh

    mp4decrypt --version

Начало работы
-------------
1. Перейдите в браузере на страницу нужного проекта, например, "Уроки истории" — https://sponsr.ru/uzhukoffa_lessons/
2. Авторизуйтесь на сайте sponsr.ru, если ещё не вошли.
3. Убедитесь, что материалы проекта доступны. Если нет, оформите подписку.
4. Получите значение cookie ``SESS`` для сайта sponsr.ru:

   a. Нажмите F12, чтобы открыть панель разработчика, перейдите на вкладку "Сеть".
   b. Загрузите простую страницу, например, https://sponsr.ru/img/new/white-logo.svg
   c. Найдите запрос ``white-logo.svg`` в списке, откройте "Заголовки запроса".
   d. В разделе ``Cookie`` скопируйте текст от ``SESS=`` до первой точки с запятой.

5. Создайте файл ``sponsrdump_auth.txt`` в корне проекта и вставьте скопированное значение ``SESS``.
6. Сохраните файл.

Во время работы приложение создаст файл ``sponsrdump.json`` в текущей директории, где хранится информация о скачанных материалах. При повторном запуске будут загружаться только новые файлы.

Варианты запуска
----------------

Запуск из командной строки
~~~~~~~~~~~~~~~~~~~~~~~~~~
Пример команды для скачивания материалов из проекта "Уроки истории". Фильтруем статьи, содержащие в заголовке "Урок ", сохраняем файлы в ``dump/``, предпочитаем видео в разрешении ``640x360`` и конвертируем текст в видео:

.. code-block:: sh

    python sponsrdump.py "https://sponsr.ru/uzhukoffa_lessons/" --title "Урок " --to dump/ --prefer-video 640x360 --text-to-video

Полный список опций:

* ``--debug``: Включить отладочные логи.
* ``--title <text>``: Фильтровать посты по заголовку.
* ``--to <path>``: Директория для сохранения (по умолчанию: ``dump/``).
* ``--prefer-video <resolution>``: Предпочитаемое разрешение видео (например, ``1080``, ``best``).
* ``--text-fmt <format>``: Формат текста (``html``, ``md``; по умолчанию: ``md``).
* ``--no-audio``: Пропустить аудиофайлы.
* ``--no-video``: Пропустить видеофайлы.
* ``--no-text``: Пропустить текстовые файлы.
* ``--no-images``: Пропустить изображения.
* ``--ffmpeg-path <path>``: Путь к ffmpeg (опционально, если в PATH).
* ``--mp4decrypt-path <path>``: Путь к mp4decrypt (опционально, если в PATH).
* ``--mp4decrypt-path <path>``: Путь к mp4decrypt.
* ``--parallel <N>``: Количество параллельных загрузок (по умолчанию: 1).
* ``--referer <url>``: Referer для видеозагрузок.
* ``--config <path>``: Путь к конфигурационному файлу.

Пример с конфигурацией:

.. code-block:: sh

    python sponsrdump.py "https://sponsr.ru/uzhukoffa_lessons/" --config config.json

Конфигурационный файл (``config.json``):

.. code-block:: json

    {
        "ffmpeg_path": "/usr/bin/ffmpeg",
        "mp4decrypt_path": "/usr/local/bin/mp4decrypt",
        "referer": "https://sponsr.ru",
        "parallel": 4
    }

Запуск из кода
~~~~~~~~~~~~~~
Пример с теми же настройками, что в командной строке:

.. code-block:: python

    from sponsrdump.dumper import SponsrDumper

    dumper = SponsrDumper(
        url='https://sponsr.ru/uzhukoffa_lessons/',
        ffmpeg_path='ffmpeg',
        mp4decrypt_path='mp4decrypt'
    )
    dumper.search(func_filter=lambda post_info: 'Урок ' in post_info['post_title'])
    dumper.dump(
        dest='dump/',
        prefer_video='640x360',
        text_to_video=True
    )

Запуск в контейнере
~~~~~~~~~~~~~~~~~~~
Полезно для запуска на NAS без установки Python 3.10. Требуется Docker.

С использованием ``make``:

.. code-block:: sh

    make run
    # Внутри контейнера: python sponsrdump.py "https://sponsr.ru/uzhukoffa_lessons/" --title "Урок " --prefer-video 640x360  --ffmpeg-path /usr/bin/ffmpeg --mp4decrypt-path /usr/local/bin/mp4decrypt

Без ``make``:

.. code-block:: sh

    docker build -t sponsrdump .
    docker run -it -v $(pwd)/sponsrdump_auth.txt:/app/sponsrdump_auth.txt -v $(pwd)/sponsrdump.json:/app/sponsrdump.json -v $(pwd)/dump:/app/dump sponsrdump python sponsrdump.py "https://sponsr.ru/uzhukoffa_lessons/" --title "Урок " --prefer-video 640x360