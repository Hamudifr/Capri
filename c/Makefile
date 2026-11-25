CC ?= cc
AR ?= ar
CFLAGS ?= -std=gnu11 -O2 -Wall -Wextra -Wpedantic -Werror
CPPFLAGS ?= -Iinclude
LDLIBS ?= -lm -lsqlite3 -pthread

.PHONY: all test clean
all: build/libccel.a build/libcapri_core.a build/libcapri_runtime.a

build:
	mkdir -p build

build/ccel.o: src/ccel.c include/ccel.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c src/ccel.c -o $@

build/capri_core.o: src/capri_core.c include/capri_core.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c src/capri_core.c -o $@

build/capri_session_store.o: src/capri_session_store.c include/capri_session_store.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -pthread -c src/capri_session_store.c -o $@

build/libccel.a: build/ccel.o
	$(AR) rcs $@ $^

build/libcapri_core.a: build/capri_core.o
	$(AR) rcs $@ $^

build/libcapri_runtime.a: build/capri_session_store.o
	$(AR) rcs $@ $^

build/test_ccel: tests/test_ccel.c build/ccel.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@

build/test_core: tests/test_core.c build/capri_core.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@

build/test_session_store: tests/test_session_store.c build/capri_session_store.o
	$(CC) $(CPPFLAGS) $(CFLAGS) -pthread $^ $(LDLIBS) -o $@

build/session_store_parity: tests/session_store_parity.c build/libcapri_runtime.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@

test: build/test_ccel build/test_core build/test_session_store
	./build/test_ccel
	./build/test_core
	./build/test_session_store

clean:
	rm -rf build
