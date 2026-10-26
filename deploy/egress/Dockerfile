# The only door to the internet: a forward proxy that allows named destinations and nothing else.
# squid starts as root only to open its port and log streams, then drops to the unprivileged squid user itself.
# trivy:ignore:AVD-DS-0002
FROM alpine:3.20
RUN apk add --no-cache squid netcat-openbsd && mkdir -p /var/run/squid && chown squid:squid /var/run/squid
COPY squid-allowlist.conf squid-open.conf allowlist.txt /etc/squid/
EXPOSE 3128
# EGRESS_MODE selects the policy file: allowlist (default) or open (public web pages, still no private addresses).
CMD ["sh", "-c", "chmod 0666 /dev/stdout /dev/stderr 2>/dev/null; exec squid -N -f /etc/squid/squid-${EGRESS_MODE:-allowlist}.conf"]
