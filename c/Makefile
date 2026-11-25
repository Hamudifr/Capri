CC ?= cc
AR ?= ar
CFLAGS ?= -std=gnu11 -O2 -Wall -Wextra -Wpedantic -Werror
CPPFLAGS ?= -Iinclude
LDLIBS ?= -lm

.PHONY: all test clean
all: build/libccel.a build/libcapri_core.a

build:
	mkdir -p build

build/ccel.o: src/ccel.c include/ccel.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c src/ccel.c -o $@

build/capri_core.o: src/capri_core.c include/capri_core.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c src/capri_core.c -o $@

build/libccel.a: build/ccel.o
	$(AR) rcs $@ $^

build/libcapri_core.a: build/capri_core.o
	$(AR) rcs $@ $^

build/test_ccel: tests/test_ccel.c build/ccel.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@

build/test_core: tests/test_core.c build/capri_core.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@

test: build/test_ccel build/test_core
	./build/test_ccel
	./build/test_core

clean:
	rm -rf build
