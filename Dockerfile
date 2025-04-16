FROM python:3.10

RUN apt-get -y update && apt-get install -y ffmpeg git cmake make g++

RUN git clone https://github.com/axiomatic-systems/Bento4.git && \
    cd Bento4 && \
    mkdir cmakebuild && \
    cd cmakebuild && \
    cmake -DCMAKE_BUILD_TYPE=Release .. && \
    make && \
    cp mp4decrypt /usr/local/bin/


WORKDIR /app
ADD sponsrdump /app/sponsrdump
ADD sponsrdump.py /app/sponsrdump.py
ADD requirements.txt /app
ADD bg.png /app

RUN pip install -r requirements.txt

VOLUME ["/app/dump"]
CMD /bin/bash