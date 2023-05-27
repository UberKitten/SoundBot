FROM python:latest
RUN apt-get install libffi-dev libnacl-dev python3-dev
COPY ./app/ /app/
WORKDIR /app/
CMD python main.py && sh web.sh