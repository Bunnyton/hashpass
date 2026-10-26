FROM busybox
COPY install-tools.sh /src/
RUN sh /src/install-tools.sh
COPY . /src
RUN sh /src/generate.sh
EXPOSE 80
CMD ["httpd", "-f", "-p", "80", "-h", "/www"]
