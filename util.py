import sys
import configparser
import os


import pymysql

class ConfigFileAccessError(Exception):
    pass

def fileExists(CONFIGFILE):
	return(os.path.isfile(CONFIGFILE))

def getConfig():

	CONFIGFILE = "./config/config.ini"
	Config = configparser.ConfigParser()
	config = {}
	if(fileExists(CONFIGFILE)):
		Config.read(CONFIGFILE)
		for section in Config.sections():
			subdict = {}
			options = Config.options(section)
			for option in options:
				key = option
				val = Config.get(section, option)
				subdict[option] = val
			config[section] = subdict
		return config

def dbConnection(host, user, password, dbname, charset="utf8mb4"):
	connection = pymysql.connect(host = host,
								user = user,
								password = password,
								db = dbname,
								charset = charset,
								cursorclass = pymysql.cursors.DictCursor)
	return connection

def queryYesNo(question, default="yes"):
	valid = {"yes": True, "y":True, "no":False, "n":False}
	if default is None:
		prompt = "[y/n]"
	elif default == "yes":
		prompt = "[Y/n]"
	elif default == "no":
		prompt = "[y/N]"
	else:
		raise ValueError("Invalid default answer")

	while True:
		sys.stdout.write(question + prompt)
		choice = input().lower()
		if default is not None and choice == '':
			return valid[default]
		elif choice in valid:
			return valid[choice]
        #else:
        #    sys.stdout.write("Please respond with 'yes' or 'no' (or 'y' or 'n').\n")

#  Flatten out a list of lists (taken from SO: http://stackoverflow.com/questions/10823877/what-is-the-fastest-way-to-flatten-arbitrarily-nested-lists-in-python
def flatten(container):
    for i in container:
        if isinstance(i, (list,tuple)):
            for j in flatten(i):
                yield j
        else:
            yield i
