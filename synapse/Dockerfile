FROM matrixdotorg/synapse:v1.121.1

COPY render_and_start.py /usr/local/bin/render_and_start.py

RUN chmod +x /usr/local/bin/render_and_start.py

ENTRYPOINT ["/usr/local/bin/render_and_start.py"]
