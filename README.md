A terminal GUI that provides a window into the current state of the transmission-daemon.

Built on curses in Python using json-rpc protocol to interface with the transmission-daemon.

If the transmission port is open, the header timestamp will be green.  It might take a few seconds for the test to complete.

Currently, upload state is not tracked.

Requires transmission-remote authentication via the transmission environment variable TR_AUTH=\<username\>:\<password\>.
