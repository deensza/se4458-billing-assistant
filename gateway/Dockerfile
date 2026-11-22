FROM kong:3.9

ENV KONG_DATABASE=off \
    KONG_PROXY_LISTEN="0.0.0.0:8000" \
    KONG_ADMIN_LISTEN="127.0.0.1:8444" \
    KONG_STATUS_LISTEN="0.0.0.0:8100" \
    KONG_PROXY_ACCESS_LOG=/dev/stdout \
    KONG_PROXY_ERROR_LOG=/dev/stderr \
    KONG_ADMIN_ERROR_LOG=/dev/stderr \
    KONG_UNTRUSTED_LUA=sandbox \
    KONG_UNTRUSTED_LUA_SANDBOX_REQUIRES=cjson.safe \
    KONG_PLUGINS=bundled

COPY kong.template.yml /etc/kong/kong.template.yml
COPY --chmod=755 entrypoint.sh /usr/local/bin/gateway-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/gateway-entrypoint.sh"]
