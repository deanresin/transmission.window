#!/usr/bin/env python3

# provides a terminal gui window into the current state of transmission-daemon
# heading timestamp will be green if port is open (checked every Y seconds)
# state color or "no torrents" color will be blue if alternate speeds are active
# transmission-daemon state updated every X seconds
# does not show upload speed
# transmission-daemon authentication in this script relies on the TR_AUTH=username:password environment variable being set

# to display all terminal colors
# for i in {0..255}; do printf "\x1b[38;5;${i}mcolour%-5i\x1b[0m" $i; if [ $(((i + 1) % 8)) -eq 0 ]; then echo; fi; done
#print(curses.COLORS)      # Usually 8 or 256
#print(curses.COLOR_PAIRS) # Often 64, 256, or 32767 depending on ncurses build

import curses
import datetime
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import requests
import os
import subprocess

class Transmission_RPC_Client:

	def __init__(self, hostport, auth=None):
    
		self.url = f'http://{hostport}/transmission/rpc'
		self.session = requests.Session()
		if auth:
			self.session.auth = auth
		else:
			self.session.auth = tuple(os.environ.get('TR_AUTH').split(":", 1))

	def send_rpc(self, method: str, arguments: dict = None) -> dict:
		payload = {"method": method}
		if arguments:
			payload["arguments"] = arguments

		# initial request
		response = self.session.post(self.url, json=payload)

		# handle 409 CSRF session id requirement
		if response.status_code == 409:
			session_id = response.headers.get("X-Transmission-Session-Id")
			if session_id:
				# update default session headers so future calls automatically include it
				self.session.headers.update(
						{"X-Transmission-Session-Id": session_id}
				)
				# retry request with valid session token
				response = self.session.post(self.url, json=payload)

		response.raise_for_status()
		return response.json()

def format_size(size):
	if size == 0:
		return 'n/a'

	# define binary powers
	KB = 1024
	MB = KB * 1024
	GB = MB * 1024
	TB = GB * 1024

	if size >= TB:
		prec = 1 if (size / TB) >= 10 else 2
		return f"{size / TB:.{prec}f}TB"
	elif size >= GB:
		prec = 1 if (size / GB) >= 10 else 2
		return f"{size / GB:.{prec}f}GB"
	elif size >= MB:
		prec = 1 if (size / MB) >= 10 else 2
		return f"{size / MB:.{prec}f}MB"
	elif size >= KB:
		prec = 1 if (size / KB) >= 10 else 2
		return f"{size / KB:.{prec}f}KB"
	else:
		return f"{int(size)}B"
	
def format_status(status, rate):

	#TR_STATUS_STOPPED = 0				# paused / Stopped.
	#TR_STATUS_CHECK_WAIT = 1			# queued in the verification queue.
	#TR_STATUS_CHECK = 2					# actively checking/verifying local files.
	#TR_STATUS_DOWNLOAD_WAIT = 3	# queued in the download queue.
	#TR_STATUS_DOWNLOAD = 4				# actively downloading.
	#TR_STATUS_SEED_WAIT = 5			# queued in the seed queue.
	#TR_STATUS_SEED = 6						# finished downloading, actively seeding.
	
	return (
		'P' if status == 0
		else 'S' if status == 6
		else 'D' if status == 4 and rate != 0
		else 'I'
	)
	
def format_rate(rate):

	# define binary powers
	KB = 1024
	MB = KB * 1024
	GB = MB * 1024
	TB = GB * 1024

	if rate >= TB:
		prec = 1 if (rate / TB) >= 10 else 2
		return f"{rate/ TB:.{prec}f}TB/s\u21c2"
	elif rate >= GB:
		prec = 1 if (rate / GB) >= 10 else 2
		return f"{rate / GB:.{prec}f}GB/s\u21c2"
	elif rate >= MB:
		prec = 1 if (rate / MB) >= 10 else 2
		return f"{rate / MB:.{prec}f}MB/s\u21c2"
	elif rate >= KB:
		prec = 1 if (rate / KB) >= 10 else 2
		return f"{rate / KB:.{prec}f}KB/s\u21c2"
	else:
		return f"{int(rate)}B/s\u21c2"
			
def get_transmission_data(client):
	
	torrents = []
	
	torrents_json = client.send_rpc(
		method="torrent-get",
		arguments={"fields": ["id", "name", "percentDone", "totalSize", "status", "rateDownload"]},
	)
	
	for torrent in torrents_json.get("arguments", {}).get("torrents", []):
	
		id = str(torrent["id"])
		name = torrent["name"]
		percent = int(f'{torrent["percentDone"] * 100:.0f}')
		size = format_size(torrent["totalSize"])
		rate = format_rate(torrent["rateDownload"])
		status = format_status(torrent["status"], torrent["rateDownload"])
		
		torrents.append(
			{
				"id": id,
				"name": name,
				"percent": percent,
				"size": size,
				"status": status,
				"rate": rate,
			}
		)
	
	alt_status = client.send_rpc(
		method="session-get",
		arguments={"fields": ["alt-speed-enabled"]}
	)
	
	# empty default dict avoids crash
	alt_active = bool(alt_status.get("arguments", {}).get("alt-speed-enabled"))
	
	return torrents, alt_active

def get_port_status(client):

	port_status_json = client.send_rpc(
		method="port-test",
		arguments={"ip_protocol": "ipv4"}
	)

	return port_status_json["arguments"].get("port-is-open", False)

def get_vpnd_timer():
	
	cmd = 'systemctl list-timers | grep -E "shutdown\.vpn\.[0-9]{6,}\.timer" | cut -d" " -f5'
	result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
  		
	return result.stdout.strip()

def draw_screen(stdscr, hostport, snapshot_mode=False):
	
	# initialize color pairs
	curses.start_color()
	curses.use_default_colors()
	# color definitions (id, text, background)
	curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
	curses.init_pair(2, curses.COLOR_WHITE, -1)
	curses.init_pair(3, curses.COLOR_YELLOW, -1)
	curses.init_pair(4, curses.COLOR_BLUE, -1)
	#
	curses.init_pair(6, curses.COLOR_YELLOW, curses.COLOR_BLUE)
	curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_GREEN)
	curses.init_pair(8, curses.COLOR_GREEN, -1)

	# hide cursor
	try:
		curses.curs_set(0)
	except curses.error:
		pass
	
	# instructs stdscr.getch() to wait Xms for key press
	# timeout happens on every stdscr.getch() call, not here 
	stdscr.timeout(150)
	
	# executor with max_workers=1 ensures only one check runs at a time
	# transmission data and port status can't run at the same time but to no ill effect
	executor = ThreadPoolExecutor(max_workers=1)
	port_future = None
	transmission_future = None

	port_is_open = False  # stores the latest check result
	
	last_transmission_time = 0
	last_port_time = 0
	
	TRANSMISSION_INTERVAL = 2.0  # refresh transmission data every <X> seconds
	# will get rate limited if this is too low
	PORT_INTERVAL = 360.0	# refresh port status every <X> seconds
	
	# redraw screen?
	update = False
	
	# create persistant transmission rpc connection
	client = Transmission_RPC_Client(hostport)
	# get transmission data right away to avoid initial delay
	# getting port status will immediately be queued 
	transmission_future = executor.submit(get_transmission_data, client)
	port_future = executor.submit(get_port_status, client)
    
	while True:
	
		current_time = time.time()

		# input check
		ch = stdscr.getch()
		if ch in (ord("q"), ord("Q"), 3):
			executor.shutdown(wait=False, cancel_futures=True)
			break
			
		# check if there is a transmission update 
		if transmission_future is not None and transmission_future.done():
			torrents, alt_active = transmission_future.result()
			if torrents is None:
				executor.shutdown(wait=False, cancel_futures=True)
				return 1
			
			update = True
			transmission_future = None  # clear the future so a new check can spawn
			last_transmission_time = current_time
			
		# only get transmission update if previous update finished
		if transmission_future is None and (current_time - last_transmission_time >= TRANSMISSION_INTERVAL):
			transmission_future = executor.submit(get_transmission_data, client)
		
		# check if there is a port status update
		# if excectuor is busy, it will queue this job and run as soon as it is free 
		if port_future is not None and port_future.done():
			port_is_open = port_future.result()
			port_future = None  # clear the future so a new check can spawn
			last_port_time = current_time
		# only check port if previous update finished
		if port_future is None and (current_time - last_port_time >= PORT_INTERVAL):
			port_future = executor.submit(get_port_status, client)
			
		# no data, no draw
		if not update:
			continue # skips current loop iteration
		
		update = False
		
		stdscr.clear()
		max_y, max_x = stdscr.getmaxyx()

		# header strings
		#vpnt_str = systemctl list-timers | grep -E "shutdown\.vpn\.[0-9]{6,}\.timer" | cut -d' ' -f5
		now_str = " - " + datetime.datetime.now().strftime("%H:%M %a, %b %d, %Y")
		header = f" ~~~ TRANSMISSION-WINDOW ~~~ "

		# draw header bar
		stdscr.addstr(1, 1, "                             ", curses.color_pair(1) | curses.A_BOLD)
		stdscr.addstr(2, 1, header, curses.color_pair(1) | curses.A_BOLD)
		stdscr.addstr(2, 30, now_str, curses.color_pair(8) if port_is_open else curses.color_pair(2))
		
		alt_color = (curses.color_pair(4) if alt_active else curses.color_pair(3))
		
		if not torrents:
			stdscr.addstr(4, 2, "no torrents", alt_color | curses.A_BOLD)
			
		else:
			# measure column widths
			id_width = max(len(t["id"]) for t in torrents)
			percent_width = max(len(str(t["percent"])) for t in torrents)
			size_width = max(len(t["size"]) for t in torrents)
			rate_width = 10

			# calculate remaining space for flexible progress/name bar
			# 8 extra spaces accounts for padding, brackets, and state column
			#extra = 9 if alt_active else 10
			extra = 10
			flex = max_x - (extra + id_width + percent_width + size_width + rate_width)
			flex = max(10, flex)  # floor width at 10 to avoid crashes on tiny windows

			

			for count, torrent in enumerate(torrents):
				row = count + 4
				if row >= max_y - 2:
					break  # stop drawing if terminal screen is too short

				# render id
				stdscr.addstr(row, 1, f"{torrent['id']:>{id_width}} ",)

				# render percentage
				stdscr.addstr(row, 2 + id_width, f"{torrent['percent']:>{percent_width}}% ", curses.color_pair(4) | curses.A_BOLD,)

				# render size
				stdscr.addstr(row, 4 + id_width + percent_width, f"{torrent['size']:>{size_width}}", curses.color_pair(3),)

				# calculate progress bar fill lengths
				done_length = int(torrent["percent"] * flex / 100)
				remaining_length = flex - done_length
				name = torrent["name"]

				filled_name = name[:done_length].ljust(done_length)
				unfilled_name = name[done_length : done_length + remaining_length].ljust(remaining_length)

				# render left bracket
				stdscr.addstr(row, 4 + id_width + percent_width + size_width, "|",)

				# render filled progress bar
				done_color = (curses.color_pair(7) if torrent["percent"] == 100 else curses.color_pair(6))
				stdscr.addstr(row, 5 + id_width + percent_width + size_width, " " + filled_name, done_color)

				# render unfilled progress bar
				stdscr.addstr(row, 5 + id_width + percent_width + size_width + done_length, unfilled_name, curses.color_pair(3) | curses.A_BOLD,)

				# render right bracket
				stdscr.addstr(row, 6 + id_width + percent_width + size_width + flex, "|",)

				# render download speed
				stdscr.addstr(row, 7 + id_width + percent_width + size_width + flex, f"{torrent['rate']:>{rate_width}}", curses.color_pair(3),)

				# render download state
				stdscr.addstr(row, 8 + id_width + percent_width + size_width + flex + rate_width, f"{torrent['status']}", alt_color,)		
				
		if not snapshot_mode:
			stdscr.addstr(4 + len(torrents) + (2 if not len(torrents) else 1), 1, f"press 'q' to quit\tvpnd: {get_vpnd_timer()}",)
			
		stdscr.refresh()

		if snapshot_mode:
			break


def main():
	snapshot = False
	if len(sys.argv) > 2 and sys.argv[2] == "1":
		snapshot = True
	
	try:
		curses.wrapper(lambda stdscr: draw_screen(stdscr, sys.argv[1], snapshot_mode=snapshot))
	except KeyboardInterrupt:
		sys.exit(0)


if __name__ == "__main__":
	main()
