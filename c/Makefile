CC ?= cc
AR ?= ar
CFLAGS ?= -std=c17 -O2 -Wall -Wextra -Wpedantic -Werror
CPPFLAGS ?= -Iinclude
LDLIBS ?= -lm

.PHONY: all test clean
all: build/libccel.a

build:
	mkdir -p build

build/ccel.o: src/ccel.c include/ccel.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c src/ccel.c -o $@

build/libccel.a: build/ccel.o
	$(AR) rcs $@ $^

build/test_ccel: tests/test_ccel.c build/ccel.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@

test: build/test_ccel
	./build/test_ccel

clean:
	rm -rf build
