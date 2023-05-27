FROM python:latest
RUN apt-get update && apt-get install -y libffi-dev libnacl-dev python3-dev
COPY ./app/ /app/
WORKDIR /app/
CMD sh web.sh && python -m app.main