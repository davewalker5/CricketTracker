FROM python:3.14-slim AS runtime

ARG APPLICATION_VERSION

COPY crickettracker-${APPLICATION_VERSION}.0 /opt/crickettracker/

WORKDIR /opt/crickettracker

RUN pip install --no-cache-dir cricket_tracker-${APPLICATION_VERSION}-py3-none-any.whl
# Fail the image build immediately if the installed wheel lacks its Streamlit script.
RUN python -c "from cricket_tracker.cli import streamlit_entrypoint; assert streamlit_entrypoint().is_file()"
RUN mkdir -p /var/opt/crickettracker

ENV CRICKET_TRACKER_ROOT=/opt/crickettracker
ENV CRICKET_TRACKER_DB=/var/opt/crickettracker/crickettracker.db

EXPOSE 8501

CMD ["cricket-tracker", "--server.address=0.0.0.0", "--server.port=8501"]
