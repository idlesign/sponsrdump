.PHONY: all build run
WORKDIR = $(shell pwd)

all: build

build:
	docker build -t sponsrdump .

run: build
	docker run -it -v $(WORKDIR):/data sponsrdump
