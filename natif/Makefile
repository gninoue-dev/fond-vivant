CFLAGS ?= -O2 -Wall -Wextra
SORTIE = ../outils

all: linux

linux: $(SORTIE)/fv-bureau

windows: $(SORTIE)/fv-bureau.exe

$(SORTIE)/fv-bureau: fv_bureau.c
	mkdir -p $(SORTIE)
	$(CC) $(CFLAGS) -o $@ $< -lX11 -lXext -lXrandr

$(SORTIE)/fv-bureau.exe: fv_bureau.c
	mkdir -p $(SORTIE)
	x86_64-w64-mingw32-gcc $(CFLAGS) -o $@ $< -luser32 -lgdi32 -mconsole -static

clean:
	rm -f $(SORTIE)/fv-bureau $(SORTIE)/fv-bureau.exe

.PHONY: all linux windows clean
