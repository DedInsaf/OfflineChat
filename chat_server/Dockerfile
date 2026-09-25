FROM python:3.12-slim

WORKDIR /app
COPY chat_server /app/chat_server
RUN mkdir -p /data

ENV OFFLINECHAT_HOST=0.0.0.0
ENV OFFLINECHAT_PORT=8787
ENV OFFLINECHAT_DATA_DIR=/data
EXPOSE 8787
VOLUME ["/data"]

CMD ["python", "-m", "chat_server.server"]
