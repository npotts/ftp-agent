ftp-agent
=========

A simple data monitoring and transfer utility that is used to automatically
move data products generated by the NCAR's Airborne Vertical Atmospheric Profiling System (AVAPS) on NASA's Global Hawk research platform.

What does it do?
================

Basically it just polls for data files that match a configurable regex 
specified in the configuration ini, attempts to ftp that data file to a configurable FTP server, and if successful, it will insert an bookkeeping
entry of the newly transfered data file into a database.  It is blocking (very small FIFO-esq data pipe), single threaded and really simple.


TODO
====

* Write the logs to the database rather than a seperate log file
* Modularize it? (does that even make sense for something this small)?
* Add in the ability to transfer via other (blocking) mechanisms
