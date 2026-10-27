# Официальный redis, но каждая запись сразу на диске (/data): для учебной базы важнее, чтобы ни
# один ключ не потерялся при docker rm -f, чем скорость.
FROM redis:7-alpine
CMD ["redis-server", "--appendonly", "yes", "--appendfsync", "always"]
