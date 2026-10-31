import sys

import uvicorn

from docsentry.app import create_app
from docsentry.config import ConfigError, load_settings
from docsentry.github.handler import make_default_handler
from docsentry.utils.logger import create_logger


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    logger = create_logger(settings.log_level)
    handler = make_default_handler(logger)
    app = create_app(settings, handler, logger)

    uvicorn.run(app, host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
