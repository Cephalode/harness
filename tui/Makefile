.PHONY: build clean run

BINARY = harness-tui
GO = go

build:
	$(GO) build -o $(BINARY) .

clean:
	rm -f $(BINARY)

run: build
	./$(BINARY)

run-remote: build
	./$(BINARY) http://metasepia:5174
