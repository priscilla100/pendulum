@ECHO OFF
IF "%JAVA_HOME%"=="" GOTO nojavahome

IF "%SALT_HOME%"=="" GOTO currenthome
IF NOT EXIST "%SALT_HOME%\bin" GOTO nohome
"%JAVA_HOME%\bin\java.exe" -cp "%SALT_HOME%\lib\antlr-2.7.5.jar;%SALT_HOME%\bin\salt.jar;%SALT_HOME%\bin" de.tum.in.salt.Compiler %1 %2 %3 %4 %5 %6 %7 %8 %9
GOTO end
:currenthome
IF NOT EXIST "bin" GOTO nohome
"%JAVA_HOME%\bin\java.exe" -cp "lib\antlr-2.7.5.jar;bin\salt.jar;bin" de.tum.in.salt.Compiler %1 %2 %3 %4 %5 %6 %7 %8 %9
GOTO end

:nojavahome
IF "%SALT_HOME%"=="" GOTO nojavacurrenthome
IF NOT EXIST "%SALT_HOME%\bin" GOTO nohome
java -cp "%SALT_HOME%\lib\antlr-2.7.5.jar;%SALT_HOME%\bin\salt.jar;%SALT_HOME%\bin" de.tum.in.salt.Compiler %1 %2 %3 %4 %5 %6 %7 %8 %9
GOTO end
:nojavacurrenthome
IF NOT EXIST "bin" GOTO nohome
java -cp "lib\antlr-2.7.5.jar;bin\salt.jar;bin" de.tum.in.salt.Compiler %1 %2 %3 %4 %5 %6 %7 %8 %9
GOTO end

:nohome
ECHO Please call SALT from its home directory or set SALT_HOME correctly.
:end
