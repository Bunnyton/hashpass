#!/bin/python3

import sys

def get_last_cmd_out(filename):
	with open(filename, 'r') as f:
		text = f.readlines()
		counter = len(text) - 1
		for line in text[::-1]:
			if 'ξ' in line:
				if counter == len(text) - 1:
					return None
				else:
					return ''.join(text[counter+1:len(text):1]).strip()
			counter -= 1

	return None

print(get_last_cmd_out(sys.argv[1]))
