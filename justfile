install:
    uv tool install --from ./packages/hanno-cli --with ./packages/hanno-core hanno-cli

reinstall:
    uv tool install --reinstall --from ./packages/hanno-cli --with ./packages/hanno-core hanno-cli

uninstall:
    uv tool uninstall hanno-cli

test:
    uv run pytest packages/ -q

lint:
    uv run ruff check packages/
