FROM python:3.10 AS builder

RUN pip install requests retry toml

COPY scheme.toml /scheme.toml

COPY build.py /build.py

RUN python3 /build.py

FROM python:3.10-alpine

RUN pip install toml

COPY --from=builder /profiles.json /profiles.json

COPY scheme.toml /scheme.toml

COPY classify.py /classify.py

ENTRYPOINT ["python3", "/classify.py"]
