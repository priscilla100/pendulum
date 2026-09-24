#!/bin/sh
nohome=
if [ -z "$JAVA_HOME" ]; then
   # no java home, salt home
   if [ -z "$SALT_HOME" ]; then
     # no java home, current home
     if [ -d "bin" ]; then
        java -cp "lib/antlr-2.7.5.jar:bin/salt.jar:bin" \
           de.tum.in.salt.Compiler $@
     else
        nohome=1
     fi
   else
      if [ -d "$SALT_HOME/bin" ]; then
         java -cp  "$SALT_HOME/lib/antlr-2.7.5.jar:$SALT_HOME/bin/salt.jar:$SALT_HOME/bin" \
            de.tum.in.salt.Compiler $@
      else
        nohome=1
      fi
  fi

else
   if [ -z "$SALT_HOME" ]; then
     # java home, current home
     if [ -d "bin" ]; then
        "$JAVA_HOME/bin/java" -cp "lib/antlr-2.7.5.jar:bin/salt.jar:bin" \
           de.tum.in.salt.Compiler $@
     else
        nohome=1
     fi
   else
      # java home, salt home
      if [ -d "$SALT_HOME/bin" ]; then
         "$JAVA_HOME/bin/java" -cp  "$SALT_HOME/lib/antlr-2.7.5.jar:$SALT_HOME/bin/salt.jar:$SALT_HOME/bin" \
            de.tum.in.salt.Compiler $@
      else
        nohome=1
      fi
  fi
fi

if [ -n "$nohome" ]; then
   echo "Please call SALT from its home directory or set SALT_HOME correctly."
fi 
