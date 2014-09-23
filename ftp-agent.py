#!/usr/bin/python
#-*- coding: utf-8 -*-
#
# Copyright (c) 2014 Nick Potts
# 
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/

import re
from sys import stdout as stdout
from time import sleep
from os import listdir
from os.path import split, join, isdir, isfile
import sqlite3
import urllib
import ftplib
import configparser
import logging


class WatcherConfig:
    """Class that returns an object with variables read from the ini file"""
    def __init__(self, cfg_file):
        """Merge items from **entries to self  Effectivly, this returns
        and object WC that has public variables."""
        cfg = configparser.SafeConfigParser()
        cfg.read(cfg_file)
        rtn={}
        rtn["mark_new_as_sent"] = cfg.getboolean("general", "mark_new_as_sent")
        rtn["loglevel"] = cfg.getint("general", "loglevel")
        rtn["logfile"]  = cfg.get("general", "logfile")
        rtn["fifo"]     = cfg.getboolean("general", "fifo")
        rtn["period"]   = cfg.getfloat("general", "period")
        rtn["regex"]    = cfg.get("general", "regex")
        rtn["data_root"]= cfg.get("general", "data_root")
        rtn["database"] = cfg.get("general", "database")
        rtn["timeout"]  = cfg.get("ftp", "timeout")
        rtn["server"]   = cfg.get("ftp", "server")
        rtn["username"] = cfg.get("ftp", "username")
        rtn["password"] = cfg.get("ftp", "password")
        rtn["path"]     = cfg.get("ftp", "folder")
        rtn["inplace"]  = cfg.getboolean("ftp", "inplace")
        # this goodness merges the self dictionary of items with 
        # the one we just read from
        self.__dict__.update(**rtn) 

        #setup logging parameters before any of the classes are initialized
        logging.basicConfig(\
            filename=self.logfile, 
            format='%(asctime)s %(module)s %(levelname)s %(message)s',
            level=self.loglevel)
        #setup Console display
        logFormatter = logging.Formatter("%(asctime)s %(module)s %(levelname)-7.7s %(message)s")
        rootLogger = logging.getLogger()
        consoleHandler = logging.StreamHandler()
        consoleHandler.setFormatter(logFormatter)
        consoleHandler.setLevel(self.loglevel)
        rootLogger.addHandler(consoleHandler)

class WatcherDatabase:
    """Class that can be queried for new data (D_P) files as well as told
    instructed that a particular file has been transfered.  It wraps around
    a transfer database"""
    def __init__(self, watcherconfig):
        """Takes the input WatcherConfig entry and opens the database.  If it
        does not already exist, it will create it and automatically shove all
        found D_P files into the "transfered" column"""
        self.config = watcherconfig
        self.db = sqlite3.connect(self.config.database)
        self.cur = self.db.cursor()
        try:
            self.cur.execute("CREATE TABLE IF NOT EXISTS transfered (rowid INTEGER PRIMARY KEY ASC, date DATETIME DEFAULT CURRENT_TIMESTAMP, fullpath TEXT, filename TEXT)")
            self.cur.execute("CREATE TABLE IF NOT EXISTS log (rowid INTEGER PRIMARY KEY ASC, date DATETIME DEFAULT CURRENT_TIMESTAMP, level INT, color TEXT, message TEXT)")
            logging.info("[DB] Database tables configured")
        except Exception as e:
            logging.critical("[DB] Could not Open database: %s", e)
            exit(-1)
        disk_products = self.__dataProductsOnDisk()
    def __dataProductsOnDisk(self):
        """Returns a dict of full-pathed data products on disk.  We only look
        directly a the send layer folders for D_P files.  EG 
        <config.data_root>/folder/<regex_match> will be found, but 
        <config.data_root>/folder/folder2/<regex_match> will not be 'found'"""
        datafiles = {}
        for d in [join(self.config.data_root, d) \
            for d in listdir(self.config.data_root) \
                if isdir(join(self.config.data_root, d))]:
            for f in [f \
                for f in listdir(d)\
                    if isfile(join(d, f)) and re.search(self.config.regex, f)]:
                datafiles[f] = join(d,f)
        logging.debug("[DB] File system contains a net of %d data files",\
                      len(datafiles))
        return datafiles
    def __dataProductsOnDatabase(self):
        """Returns a dict of full-pathed data products on the database"""
        rtn={}
        cnt = 0;
        try:
            for row in self.cur.execute("SELECT filename, fullpath FROM transfered"):
                cnt += 1
                rtn[row[0]] = row[1]
            logging.debug("[DB] Database contains a net of %d data files",\
                          cnt)
        except Exception as e:
            logging.error("[DB] Error pulling xfers from database: %s", e)
        return rtn
    def addAllDiskProducts(self):
        """This helper function marks all soundings found by dataProducts()
        as "sent".  This is mostly just a helper function to shove any data
        created via ground tests into the database"""
        for (f, fp) in self.dataProducts().items():
            self.addProduct( (f, fp))
    def dataProducts(self):
        """Returns a dictionary of full-pathed files that match the supplied 
        reged that are not in the database yet are preset on disk"""
        existing = self.__dataProductsOnDisk()
        rtn = existing.copy()
        transfered = self.__dataProductsOnDatabase()
        for (f, fp) in existing.items():
            for (d, dp) in transfered.items():
                if f == d:
                    del rtn[f]
        if len(rtn) != 0:
            logging.info("[DB] The following items are on the file system,\
                           but not in the database.")
            for d in rtn.keys():
                logging.info("[DB] - %s", d)
        return rtn
    def addProduct(self, transfered):
        """Adds the transfered couple of (filename, full-path) to the database as 
        transfered."""
        try:
            self.cur.execute("INSERT INTO transfered (filename, fullpath) VALUES (?, ?)", transfered)
            self.db.commit()
            logging.info("[DB] Inserted %s into the transfered database", transfered[0] )
            return True
        except Exception as e:
            logging.error("[DB] Unable to insert data into database: %s", e)
        return False
class WatcherFTP:
    def __init__(self, watcherconfig):
        """Configure the FTP send logic"""
        self.config = watcherconfig
    def send(self, tuple):
        """Sends the file pointed to by <fullpath> to the FTP location
        specified in self.config"""
        try:
            logging.debug("[FTP] Starting FTP process to send %s", tuple[1] )
            #create FTP object
            ftp = ftplib.FTP()

            #connect
            ftp.connect(self.config.server, 21, int(self.config.timeout))
            logging.debug("[FTP] Connected to %s", self.config.server )

            #login
            ftp.login(self.config.username, self.config.password)
            logging.debug("[FTP] Logged in as '%s'", self.config.username )

            #change working dir on the server
            ftp.cwd(self.config.path)
            logging.debug("[FTP] CWD to %s", self.config.path )

            #open local file
            tosend = open(tuple[1], 'rb')
            logging.debug("[FTP] Opened %s", tuple[1] )

            if self.config.inplace: #updating the file inplace
                # send the file
                ftp.storbinary("STOR %s" % tuple[0], tosend)
                logging.debug("[FTP] Uploaded as %s", tuple[0])
            else:
                # send the file
                ftp.storbinary("STOR %s.tmp" % tuple[0], tosend)
                logging.debug("[FTP] Uploaded as %s.tmp", tuple[0])

                # rename
                ftp.rename("%s.tmp" % tuple[0], tuple[0])
                logging.debug("[FTP] Renamed as %s.tmp->%s", tuple[0], tuple[0])

            #cleanup
            tosend.close()
            ftp.quit()
            logging.info("[FTP] Successfully FTP'd %s.", tuple[1])

            return True
        except Exception as e:
            logging.error("[FTP] Unable to send file: '%s'", e)
            return False
class WatcherOverlord:
    """Master class that drives the other components"""
    def __init__(self, config_filename):
        """Initialize and start process.  config_filename is the path to
        the INI file to use as the configuration.  markAllOnFirstRun will push
        ALL data files found into the database before starting."""
        self.config = WatcherConfig(config_filename)
        try:
            self.db = WatcherDatabase(self.config)
            self.ftp = WatcherFTP(self.config)
        except Exception as e:
            logging.critical("[Overlord] Unable to initialize elements: %s", e)
            exit(1)

        try:
            #If true, we mark all the found data files as transfered
            if self.config.mark_new_as_sent:
                logging.warning("[OVERLORD] Marking all data files on the file system\
                                 as transfered...")
                self.db.addAllDiskProducts()
        except Exception as e:
            logging.critical("[OVERLOAD] Could not mark data as transfered")
        #start the mainloop
        self.loop()

    def loop(self):
        """Look for new data files, send them, and if they work, mark 
        them as transfered by placing them in the database"""
        logging.info("[OVERLORD] Entering Normal Run Operations")
        while True:
            try:
                #delay as the first order
                sleep(self.config.period)

                #look for new data files
                data = self.db.dataProducts()
                order = list(data.keys())
                order.sort()
                if not self.config.fifo:
                    order.reverse()

                if len(order) == 0:
                    logging.info(\
                        "[OVERLORD] No Files found.  Sleeping for %d second(s)",
                        self.config.period)
                    continue

                #now try to send them.
                for product in order:
                    data_product = (product, data[product]) 
                    if self.ftp.send( data_product ):
                        self.db.addProduct(data_product)
                        logging.info("[OVERLORD] FTP'd %s to %s", product, self.config.server)
            except Exception as e:
                logger.critical("[OVERLORD] Error in main loop %s", e)

wo = WatcherOverlord("ftp-agent.ini")
