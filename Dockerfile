FROM python:latest
RUN apt-get update && apt-get install -y libffi-dev libnacl-dev python3-dev

WORKDIR /app/
COPY ./requirements.txt /app/
RUN pip install -r requirements.txt

COPY ./web.sh /app/
COPY ./app/ /app/app/
CMD sh web.sh && python -m app.main