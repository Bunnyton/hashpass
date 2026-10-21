FROM busybox:latest
COPY www /www
EXPOSE 80
CMD ["httpd", "-f", "-p", "80", "-h", "/www"]
