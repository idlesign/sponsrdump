FROM python:3.10

RUN apt-get -y update
RUN apt-get install -y ffmpeg

ADD src/sponsrdump/bg.png .
ADD requirements.txt .
RUN pip install -r requirements.txt

ADD src/sponsrdump/sponsrdump.py .

VOLUME ["/dump"]
CMD /bin/bash
