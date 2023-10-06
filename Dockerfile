FROM python:3.11

USER root
RUN apt-get -f install
RUN apt-get update
RUN apt-get install -y virtualenv

ENV APP_HOME /app
RUN virtualenv -p python3.11 $APP_HOME/venv
ENV VIRTUAL_ENV $APP_HOME/venv
ENV PATH $APP_HOME/venv/bin:$PATH
WORKDIR $APP_HOME

ADD requirements.txt $APP_HOME/requirements.txt
RUN pip install -r $APP_HOME/requirements.txt

COPY ./resources $APP_HOME/resources
COPY ./src $APP_HOME/src

# ENTRYPOINT ["gunicorn", "src.main:app", "--bind=:8080", "--workers=1"]
ENTRYPOINT ["python", "-m", "src.main"]
