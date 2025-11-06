FROM python:3.12-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /bin/

RUN apt-get -y update
RUN apt-get install -y ffmpeg

ADD src/ src/
ADD README.md .
ADD pyproject.toml .
RUN uv sync
RUN uv tool install --force -e .

RUN uvx sponsrdump --help

VOLUME ["/dump"]
CMD ["/bin/bash"]
