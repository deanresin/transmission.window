#!/usr/bin/env python3

import curses
import datetime
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

def get_transmission_data(hostport):

	try:
		# get session info to check alternate speed limit status
		session = subprocess.check_output(
			["transmission-remote", hostport, "--authenv", "--session-info"],
			text=True,
			stderr=subprocess.DEVNULL,
		)
		# True if alternate speed limits are active
		alt_active = "Download speed limit: 0" not in session
		
		# get torrent info
		info = subprocess.check_output(
			["transmission-remote", hostport, "--authenv", "-t", "all", "--info"],
			text=True,
			stderr=subprocess.DEVNULL,
		)
	except (subprocess.CalledProcessError, FileNotFoundError):
		return None, False
	
	# parsing info
	# get ids
	ids = re.findall(r"^\s*Id:\s*(\d+)", info, re.MULTILINE)
	if not ids:
		return [], alt_active

	names = re.findall(r"^\s*Name:\s*(.*)$", info, re.MULTILINE)
	perc_raw = re.findall(r"^\s*Percent Done:\s*([\d\.]+)%", info, re.MULTILINE)
	sizes_raw = re.findall(r"^\s*Total size:\s*([^(]*) \(.*$", info, re.MULTILINE)
	states_raw = re.findall(r"^\s*State:\s*(.*)$", info, re.MULTILINE)
	dspeeds_raw = re.findall(r"^\s*Download Speed:\s*(.*)$", info, re.MULTILINE)

	torrents = []
    
  # format data
	for i in range(len(ids)):
  	
		try:
			progress = int(float(perc_raw[i]))
		except (IndexError, ValueError):
			progress = 0
  		
		# S when Idle with zero downloaded makes no sense
		state = "I" if "Idle" in states_raw[i] else "S" if "Seeding" in states_raw[i] else ("D" if "Down" in states_raw[i] else "P")

		if "None" in sizes_raw[i]:
			size = "n/a"
		else:
			size = sizes_raw[i].replace(" ", "") 

		# speed string with unicode arrow ⇂
		speed = dspeeds_raw[i].replace(" ", "") + "\u21c2"

		torrents.append(
			{
				"id": ids[i],
				"name": names[i],
				"progress": progress,
				"size": size,
				"state": state,
				"speed": speed,
			}
		)

	return torrents, alt_active

def get_port_status(hostport):
	port_open = False
	try:
		# test if port is open
		port_status = subprocess.check_output(
			["transmission-remote", hostport, "--authenv", "-pt"],
			text=True,
			stderr=subprocess.DEVNULL,
		)
		# True if alternate speed limits are active
		port_open = "Port is open: Yes" in port_status
	except (subprocess.CalledProcessError, FileNotFoundError):
		pass

	return port_open


def draw_screen(stdscr, hostport, snapshot_mode=False):
	# initialize color pairs
	curses.start_color()
	curses.use_default_colors()

	# color definitions
	# 1: header (white text on blue background)
	curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
	# 2: ids & dividers (dark gray / bright black)
	curses.init_pair(2, curses.COLOR_WHITE, -1)
	# 3: percent / speed / size (yellow)
	curses.init_pair(3, curses.COLOR_YELLOW, -1)
	# 4: alt speed active (blue)
	curses.init_pair(4, curses.COLOR_BLUE, -1)
	# 5: alt speed inactive (dark yellow)
	curses.init_pair(5, curses.COLOR_YELLOW, -1)
	# 6: in-progress bar (yellow text on blue background)
	curses.init_pair(6, curses.COLOR_YELLOW, curses.COLOR_BLUE)
	# 7: finished 100% bar (white text on green background)
	curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_GREEN)
	# 8: port open status
	curses.init_pair(8, curses.COLOR_GREEN, -1)

	# hide cursor
	try:
		curses.curs_set(0)
	except curses.error:
		pass
	
	stdscr.timeout(50)
	
	# preserve state for ui rendering
	torrents, alt_active = [], False
	
	# executor with max_workers=1 ensures only one check runs at a time
	executor = ThreadPoolExecutor(max_workers=1)
	port_future = None
	port_is_open = False  # stores the latest check result
	transmission_future = None

	last_transmission_time = 0
	last_port_time = 0
	
	TRANSMISSION_INTERVAL = 1.0  # refresh transmission data every X.0 seconds
	PORT_INTERVAL = 15.0	# refresh port status every Y.0 seconds
	
	update = False
    
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
			transmission_future = executor.submit(get_transmission_data, hostport)
			
		# there will be no data on first iteration	
		if not update:
			continue
		
		update = False
		
		stdscr.clear()
		max_y, max_x = stdscr.getmaxyx()

		# header strings
		now_str = " - " + datetime.datetime.now().strftime("%H:%M %a, %b %d, %Y")
		header = f" ~~~ TRANSMISSION-WINDOW ~~~ "

		# draw header bar
		stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
		stdscr.addstr(1, 1, "                             ")
		stdscr.addstr(2, 1, header)
		stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
    
    # check if there is a port status update 
		if port_future is not None and port_future.done():
			port_is_open = port_future.result()
			port_future = None  # clear the future so a new check can spawn
			last_port_time = current_time
		# only check port if previous update finished
		if port_future is None and (current_time - last_port_time >= PORT_INTERVAL):
			port_future = executor.submit(get_port_status, hostport)			
		
		stdscr.addstr(2, 30, now_str, curses.color_pair(8) if port_is_open else curses.color_pair(2))
		#stdscr.addstr(2, 30, now_str)
		
		if not torrents:
			color = curses.color_pair(3) if alt_active else curses.color_pair(4)
			stdscr.addstr(4, 2, "no torrents", color | curses.A_BOLD)
			
		else:
			# measure column widths
			id_width = max(len(t["id"]) for t in torrents)
			prog_width = max(len(str(t["progress"])) for t in torrents)
			size_width = max(len(t["size"]) for t in torrents)
			speed_width = 11

			# calculate remaining space for flexible progress/name bar
			# 8 extra spaces accounts for padding, brackets, and state column
			extra = 10 if alt_active else 9
			flex = max_x - (extra + id_width + prog_width + size_width + speed_width)
			flex = max(10, flex)  # Floor width at 10 to avoid crashes on tiny windows

			alt_color = (curses.color_pair(3) if alt_active else curses.color_pair(4))

			for idx, t in enumerate(torrents):
				row = idx + 4
				if row >= max_y - 2:
					break  # stop drawing if terminal screen is too short

				# render id
				stdscr.addstr(row, 1, f"{t['id']:>{id_width}} ",)

				# render percentage
				stdscr.addstr(row, 2 + id_width, f"{t['progress']:>{prog_width}}% ", curses.color_pair(4) | curses.A_BOLD,)

				# render size
				stdscr.addstr(row, 4 + id_width + prog_width, f"{t['size']:>{size_width}}", curses.color_pair(3),)

				# calculate progress bar fill lengths
				pb_len = int(t["progress"] * flex / 100)
				npb_len = flex - pb_len
				name = t["name"]

				filled_name = name[:pb_len].ljust(pb_len)
				unfilled_name = name[pb_len : pb_len + npb_len].ljust(npb_len)

				# render left bracket
				stdscr.addstr(row, 4 + id_width + prog_width + size_width, "|",)

				# render filled progress bar
				pb_color = (curses.color_pair(7) if t["progress"] == 100 else curses.color_pair(6))
				stdscr.addstr(row, 5 + id_width + prog_width + size_width, " " + filled_name, pb_color)

				# render unfilled progress bar
				stdscr.addstr(row, 5 + id_width + prog_width + size_width + pb_len, unfilled_name, curses.color_pair(3) | curses.A_BOLD,)

				# render right bracket
				stdscr.addstr(row, 6 + id_width + prog_width + size_width + flex, "|",)

				# render download speed
				stdscr.addstr(row, 7 + id_width + prog_width + size_width + flex, f"{t['speed']:>{speed_width}}", curses.color_pair(3),)

				# render download state
				stdscr.addstr(row, 8 + id_width + prog_width + size_width + flex + speed_width, f"{t['state']}", alt_color,)		
				
		if not snapshot_mode:
				
			stdscr.addstr(
				4 + len(torrents) + (2 if not len(torrents) else 1), 
				1, 
				"press 'q' or ctrl-c to quit",
			)
			
		stdscr.refresh()

		if snapshot_mode:
			break
   
		# check for user quit keys ('q' or Ctrl+C) with 2-second timeout
		stdscr.timeout(2000)
		ch = stdscr.getch()
		if ch in (ord("q"), ord("Q"), 3):  # 3 is ASCII for Ctrl+C
			executor.shutdown(wait=False, cancel_futures=True)
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
