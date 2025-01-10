FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get -yq update \
    && apt-get -yq install net-tools iproute2 tcpdump iputils-ping procps grep less curl wget iperf3 traceroute python3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \ 
    && mkdir -p -v /scripts

CMD ["bash"]
