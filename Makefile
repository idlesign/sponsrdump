.PHONY: all build run
WORKDIR = $(shell pwd)

all: build

build:
	docker build -t sponsrdump .

run: build
	docker run -it -v $(WORKDIR)/sponsrdump_auth.txt:/sponsrdump_auth.txt -v $(WORKDIR)/sponsrdump.json:/sponsrdump.json -v $(WORKDIR)/dump:/dump sponsrdump
