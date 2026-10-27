# The only door to the internet: a forward proxy that allows named destinations and nothing else.
FROM alpine:3.20
RUN apk add --no-cache squid netcat-openbsd && mkdir -p /var/run/squid && chown squid:squid /var/run/squid
COPY squid-allowlist.conf squid-open.conf allowlist.txt /etc/squid/
USER squid
EXPOSE 3128
# EGRESS_MODE selects the policy file: allowlist (default) or open (public web pages, still no private addresses).
CMD ["sh", "-c", "exec squid -N -f /etc/squid/squid-${EGRESS_MODE:-allowlist}.conf"]
