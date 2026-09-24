FROM eclipse-temurin:17-jdk

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ghc \
        unzip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV SALT_HOME=/opt/salt
WORKDIR /opt/salt

COPY salt_extract/ /opt/salt/

RUN cp /opt/salt/config/hs.properties.template /opt/salt/config/hs.properties \
    && sed -i 's|^hs.interpreter.*|hs.interpreter = ghc|' /opt/salt/config/hs.properties \
    && sed -i 's|^ghc.path.*|ghc.path = /usr/bin|' /opt/salt/config/hs.properties \
    && sed -i 's|^ghc.command.*|ghc.command = runghc|' /opt/salt/config/hs.properties \
    && sed -i 's|^ghc.options.*|ghc.options = -w|' /opt/salt/config/hs.properties \
    && chmod +x /opt/salt/salt.sh \
    && for f in /opt/salt/hs/*.hs; do \
         sed -i 's/\r$//' "$f" ; \
         sed -i \
           -e 's|^import List$|import Data.List|' \
           -e 's|^import Maybe$|import Data.Maybe|' \
           -e 's|^import IO$|import System.IO|' \
           "$f"; \
       done

RUN printf '%s\n' \
    '#!/bin/sh' \
    'exec java -cp "$SALT_HOME/lib/antlr-2.7.5.jar:$SALT_HOME/bin/salt.jar:$SALT_HOME/bin" de.tum.in.salt.Compiler "$@"' \
    > /usr/local/bin/salt \
    && chmod +x /usr/local/bin/salt

WORKDIR /work
ENTRYPOINT ["/usr/local/bin/salt"]
CMD ["-h"]
