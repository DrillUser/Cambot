@echo off
cls
title Admin policy script
set iii=0
set Dom=local
Set IPaddr=0
Set gw=0
set MAC=00-00-00-00-00-00
set addr_type=Dynamic
set Ugly_words=���頩��� � ��襬� ��⥬���� ������������.
set Unsupported=��ਯ� �� �����ন���� ������ ����樮���� ��⥬�.
set MakeSettings=�������� �ந�������� ����ன�� ...

echo.

echo ��� ��������:		%computername% 
echo ��� ���짮��⥫�:	%USERNAME%




if /I NOT %USERDOMAIN%==%COMPUTERNAME% set Dom=%USERDOMAIN%
echo �����:			%Dom%				

if "%COMPUTERNAME%"=="TS1" goto quit
if "%COMPUTERNAME%"=="TS2" goto quit
if "%COMPUTERNAME%"=="TS3-parus" goto quit
if "%COMPUTERNAME%"=="TS4" goto quit


rem -----  ����������� ������������ �������


for /f "tokens=2 delims=[] usebackq" %%A in (`ver`) do ( 
	@for /f "tokens=2 usebackq" %%a in (`@echo %%A`) do @set osver=%%a )
 
if "%osver:~0,5%"=="5.00." (echo ����樮���� ��⥬�:	Windows 2000 & goto w2000)
if "%osver:~0,4%"=="5.1." (echo ����樮���� ��⥬�:	Windows XP & goto xp)
if "%osver:~0,4%"=="5.2." (echo ����樮���� ��⥬�:	Windows 2003 or XP 64-bit & goto w2003) 
if "%osver:~0,4%"=="6.0." (echo ����樮���� ��⥬�:	Windows 2008 or Vista & goto w2008) 
if "%osver:~0,4%"=="6.1." (echo ����樮���� ��⥬�:	Windows 7 & goto w7)
if "%osver:~0,4%"=="6.2." (echo ����樮���� ��⥬�:	Windows 8 & goto w8)
if "%osver:~0,4%"=="6.3." (echo ����樮���� ��⥬�:	Windows 8.1 & goto w81) 
if "%osver:~0,5%"=="10.0." (echo ����樮���� ��⥬�:	Windows 10 & goto w10) else (echo �������⭠� ��⥬� ! & goto quit)

:w2000
set d1=2
set a1="��"
set a2="���"
goto m0


:xp
:w2003
set d1=3
set a1="��"
set a2="���"
set net_str1=netsh interface ip set dns
set net_str2=netsh interface ip add dns
set a3=addr
goto m0

:w2008
:w7
:w8
:w81
:w10
set d1=3
set a1="��"
set a2="���"
set net_str1=netsh interface ipv4 set dnsservers
set net_str2=netsh interface ipv4 add dnsservers
set a3=address
:m0


rem  ----- ����������� ����� � ������ ��������� ����������

for  /f "tokens=1-4 usebackq" %%A in (`route print 0.0.0.0`) do (
	if "%%A%%B"=="0.0.0.00.0.0.0" (set gw=%%C & set IPaddr=%%D & goto m01))
:m01
set IPaddr=%IPaddr:~0,-1%
set gw=%gw:~0,-1%

if "%IPaddr%"=="" (
	echo. & echo �ணࠬ�� �� ����� �����㦨�� ������祭�� � ��. & echo %Ugly_words% & goto quit)
echo IP-����^:		%IPaddr% 


rem  -----  �����������  MAC-������ ��������� ����������

echo. > %TEMP%\scr_inf.lan
if "%osver:~0,2%"=="5." (ipconfig /all >> %TEMP%\scr_inf.lan ) else (
	for /f "tokens=* usebackq" %%A in (`ipconfig /all`) do @(echo %%A >> %TEMP%\scr_inf.lan ))


for /f "tokens=1-2 delims=:" %%A in (%TEMP%\scr_inf.lan) do (
	set /A iii+=1 & for /f "tokens=1 usebackq delims=( " %%a in ('%%B') do (
		if %%a==%IPaddr% (goto m1)))
:m1

set /A iii=iii-d1

:m19
for /f "tokens=1-2 skip=%iii% delims=:" %%A in (%TEMP%\scr_inf.lan) do (
	for /f "tokens=1 usebackq" %%a in ('%%B') do (
		if "%%a"==%a1% (set /A iii-=1 & goto m19) else (
		if "%%a"==%a2% (set /A iii-=1 & goto m19) else (set MAC=%%a & goto m21))))	
:m21
set MAC=%MAC:~0,-1%

rem  -----  �����������: ����� ����������� ��� ������������

set /A iii+=1
for /f "tokens=1-2 skip=%iii% delims=:" %%A in (%TEMP%\scr_inf.lan) do (
	for /f "tokens=1 usebackq" %%a in ('%%B') do (
		(if "%%a"==%a2% (set addr_type=Static)) & goto m14)) 
:m14

echo ��� ����:		%addr_type%		
echo MAC-����:		%MAC%

del /Q %TEMP%\scr_inf.lan

rem  ----- ����������� ����� ��������� ����������

if "%osver:~0,5%"=="5.00." (echo. & echo %Unsupported% & echo %Ugly_words% & goto quit) 


for /f "tokens=1-3 usebackq delims=," %%A in (`getmac /v /NH /FO CSV`) do (
	if %%C=="%MAC%" (set ifname=%%A & goto m2))
:m2

echo ��⨢�� ������:	%ifname%
echo.

rem  ----- ��������

if not %Dom%==local (
	if not %Dom%==free.miit (
		(echo ��� ��設� ��室���� � ������ %Dom%,) & (
		echo �������� �� ����ன�� ����� ⮫쪮 IT ���ᮭ�� �⮣� ������.) & (
		echo %Ugly_words% & goto quit)))

if %IPaddr:~0,7%==10.242. (
	if not %IPaddr:~0,11%==10.242.120. (
			(echo ��� �������� ������祭 � ��� ����.) & (
			 echo.) & (echo %MakeSettings%) & (
			 %net_str1% %ifname% dhcp register=both > nul) & (goto m3)))
			 

echo ��� �������� ������祭 � ���ᮡ������ �� ���ࠧ�������,  
echo ����� �⤥���� �� ��饩 �� ��� ���� ���।�⢮� ������⨧���, ����
echo ����� �� ������祭� � ��� ����.
echo ������ ��⮬���᪨ ���ࠧ㬥����, �� � ��襬 ���ࠧ������� ������ ����
echo ᢮� IT ���ᮭ��. 
echo ������ �ணࠬ�� ����� ᤥ���� ������  �ந����� ����室��� ����ன�� 
echo ᠬ����⥫쭮, �� �� �⮬ ���� �� ��������� �����-���� �ᮡ���� ��� 
echo ��襩 ��� ����ன��. ���⮬� ४��������� �������� � ��訬 ᯥ樠���⠬, 
echo �᫨ ⠪��� �������.
echo.
echo �⮡� ��������� �ணࠬ�� �ந����� ����ன�� - ������ ���� �������.
echo �⮡� �⪠������ - ���� ���ன� �� ����.
echo.
 
pause > nul

echo %MakeSettings%
%net_str1% %ifname% static %a3%=10.242.100.4 register=both > nul
%net_str2% %ifname% %a3%=195.245.205.5 index=2 > nul

:m3
rem ------- ��������� ������, wsus, � �������

rem		���������� � Search List
rem echo ��⠭���� DNS-���䨪� ...
REG ADD HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters /v SearchList /t REG_SZ /d free.miit /f 1>nul 2>nul

rem 		��������� ����������
rem echo ��⠭���� ���᪠ PROXY-�ࢥ� ...
REG DELETE "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v AutoConfigURL /f  1>nul 2>nul
REG ADD "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0x0 /f 1>nul 2>nul
REG DELETE "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /f 1>nul 2>nul
REG DELETE "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /f 1>nul 2>nul
REG ADD "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings\Connections" /v DefaultConnectionSettings /t REG_BINARY /d 4600000006000000090000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000 /f 1>nul 2>nul



rem 		������ ������ "DHCP-������"
rem echo ��⠭���� ������� �㦡� "DHCP-������" ... 
REG ADD HKLM\SYSTEM\CurrentControlSet\Services\Dhcp /v Start /t REG_DWORD /d 0x2 /f 1>nul 2>nul

rem 		Disable Autorun
rem echo �⪫�祭�� ��⮧���᪠ �� ��� ���⥫�� ...
REG ADD HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer /v NoDriveTypeAutoRun /t REG_DWORD /d 0xff /f 1>nul 2>nul
REG ADD HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer /v NoDriveTypeAutoRun /t REG_DWORD /d 0xff /f 1>nul 2>nul

rem 		Disable IPv6
rem echo �⪫�祭�� IPv6 ...
REG ADD HKLM\SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters /v DisabledComponents /t REG_DWORD /d 0xffffffff /f 1>nul 2>nul


rem 		WSUS settings
rem echo ��⠭���� "����� ���������� Windows" ...
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate /v WUServer /t REG_SZ /d http:^/^/germes:8530 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate /v WUStatusServer /t REG_SZ /d http:^/^/germes:8530 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU /v UseWUServer /t REG_DWORD /d 0x1 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU /v AutoInstallMinorUpdates /t REG_DWORD /d 0x1 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU /v IncludeRecommendedUpdates /t REG_DWORD /d 0x1 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU /v NoAutoUpdate /t REG_DWORD /d 0x0 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU /v AUOptions /t REG_DWORD /d 0x4 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU /v ScheduledInstallDay /t REG_DWORD /d 0x0 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU /v ScheduledInstallTime /t REG_DWORD /d 0x10 /f 1>nul 2>nul
REG ADD HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU /v NoAutoRebootWithLoggedOnUsers /t REG_DWORD /d 0x1 /f 1>nul 2>nul

rem 		��������� ������������� �������
rem echo ��⠭���� ᨭ�஭���樨 �६��� ...
w32tm /config /manualpeerlist:femida /syncfromflags:MANUAL /update 1>nul 2>nul

echo.
echo ����ன�� �ந������� ...
:quit
echo.
echo.
echo. 
pause

