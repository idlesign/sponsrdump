.PHONY: all build run
WORKDIR = $(shell pwd)

all: build

build:
	docker build -t sponsrdump .

run: build
	docker run -it -v $(WORKDIR)/sponsrdump_auth.txt:/app/sponsrdump_auth.txt -v $(WORKDIR)/sponsrdump.json:/app/sponsrdump.json -v $(WORKDIR)/dump:/app/dump sponsrdump /bin/bash