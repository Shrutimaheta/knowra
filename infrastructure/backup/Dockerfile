FROM postgres:16-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends age && rm -rf /var/lib/apt/lists/*
COPY backup.sh /usr/local/bin/knowra-backup
COPY restore-drill.sh /usr/local/bin/knowra-restore-drill
RUN chmod 755 /usr/local/bin/knowra-backup
ENTRYPOINT ["bash", "/usr/local/bin/knowra-backup"]
