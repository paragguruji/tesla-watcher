FROM gcr.io/google-appengine/python

USER root
RUN apt-get update
RUN apt-get install -y wget  \
    gconf-service  \
    libasound2  \
    libatk1.0-0  \
    libcairo2  \
    libcups2  \
    libfontconfig1  \
    libgdk-pixbuf2.0-0  \
    libgtk-3-0  \
    libnspr4  \
    libpango-1.0-0  \
    libxss1  \
    fonts-liberation  \
    libappindicator1  \
    libnss3  \
    lsb-release  \
    xdg-utils \
    libu2f-udev \
    libvulkan1

RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
RUN dpkg -i google-chrome-stable_current_amd64.deb; apt-get -fy install


ENV APP_HOME /app
WORKDIR $APP_HOME

RUN virtualenv -p python3.11 $APP_HOME/venv
ENV VIRTUAL_ENV $APP_HOME/venv
ENV PATH $APP_HOME/venv/bin:$PATH

ADD requirements.txt $APP_HOME/requirements.txt
RUN pip install -r $APP_HOME/requirements.txt

COPY ./src $APP_HOME/src
COPY ./resources $APP_HOME/resources

USER cnb

ENTRYPOINT ["python", "-m", "src/main.py"]
