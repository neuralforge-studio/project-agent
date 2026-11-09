"""A tmux client on a pty for the test server: attaches to SESSION and discards its output until killed.
usage: python pty_client.py SOCKET SESSION"""
import fcntl, os, pty, select, struct, sys, termios
sock, session = sys.argv[1], sys.argv[2]
pid, fd = pty.fork()
if pid == 0:
    os.environ["TERM"] = "xterm-256color"
    os.environ.pop("TMUX", None)
    os.execvp("tmux", ["tmux", "-S", sock, "attach-session", "-t", session])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
while True:
    r, _, _ = select.select([fd], [], [], 5)
    if r:
        try:
            if not os.read(fd, 65536):
                break
        except OSError:
            break
