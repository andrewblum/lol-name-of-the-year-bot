import logging

from .bot import NameBot
from .config import load_config


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    cfg = load_config()
    NameBot(cfg).run(cfg.discord_token, log_handler=None)


if __name__ == '__main__':
    main()
