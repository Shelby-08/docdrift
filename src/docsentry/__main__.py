import sys

import uvicorn

from docsentry.app import create_app
from docsentry.config import ConfigError, load_settings
from docsentry.utils.logger import create_logger


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    logger = create_logger(settings.log_level)
    # handler=None wires the real pipeline (retrieval -> analysis -> Check Run).
    app = create_app(settings, None, logger)

    uvicorn.run(app, host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
