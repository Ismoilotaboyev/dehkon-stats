# Local Bot API server (official tdlib/telegram-bot-api, packaged by aiogram) + private file server.
# Railway service root directory: telegram-bot-api/ . No public domain is needed.
FROM aiogram/telegram-bot-api:latest
USER root
# python3 runs file_server.py (stdlib only). The base image is Alpine; apt fallback just in case.
RUN if command -v apk >/dev/null 2>&1; then apk add --no-cache python3; \
    else apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*; fi
COPY file_server.py /opt/file_server.py
COPY start.sh /opt/start.sh
RUN chmod +x /opt/start.sh
ENTRYPOINT ["/opt/start.sh"]
