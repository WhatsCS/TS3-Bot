"""
Copyright (c) 2016, Evan Valmassoi
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following
disclaimer in the documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products
derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
import sys
import logging
import ruamel.yaml
import lib.ts3
from logging.handlers import TimedRotatingFileHandler
from lib.rblwatch import RBLSearch


# Set up config
class Config(object):
    """
    Create a callable class for getting the needed variables for which ever
    config option that is required.
    Each section of the config is stored inside of a dict for said section.
    It will be put through a parser to insure that required sections are present
    in the config file.

    Has a method for easy reloading of config without having to fully restart the bot

    Usage:
        config = Setup("config.yaml") to assign config file
        config.load() to reload
    """
    def __init__(self, filename):
        self.ts3server = {}
        self.logsection = {}
        self.actions = {}
        self.filename = filename
        self.load()
        self.loginit()

    def load(self):
        with open(self.filename, 'r') as fp:
            data = ruamel.yaml.load(fp)
        self.ts3server = data['TS3Server']
        self.logsection = data['Logging']
        self.actions = data['Actions']

    def loginit(self):
        """
        Initializing the logging function, will be called at the start along
        with anything else that needs to be initialized.
        :return:
        """
        fname = self.logsection.get("logFile", __name__)

        # Set log name to what ever the bot name is
        self.logger = logging.getLogger(self.ts3server['botNick'])

        # Set log level to which ever is in the config
        try:
            self.logger.setLevel(self.logsection['logLevel'].upper())
        except AttributeError:
            print("logLevel not set, please set before starting the bot.")

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(name)10s | %(levelname)8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Create a file handler and add it to the logger
        # "midnight" means it will change every day
        # backupCount is log life time
        handler = TimedRotatingFileHandler(fname, "midnight", backupCount=14)
        # Add formatter to handler
        handler.setFormatter(formatter)
        # Add the handler to the logger
        self.logger.addHandler(handler)

        # repeat but for console logging
        chandler = logging.StreamHandler()
        chandler.setLevel(self.logsection['logLevel'].upper())
        chandler.setFormatter(formatter)
        self.logger.addHandler(chandler)

        # Let everyone know that shit is working now.
        self.logger.debug("Logging Initialized")


def kickban(ban, kick, clid, ts3conn):
    """
    Global function for kicking and/or banning.
    Send in which you want and the function will do the rest
    :return:
    """
    if ban:
        ts3conn.banclient(clid=clid, time=config.actions['banTime'], banreason=config.actions['reason'])
        config.logger.info("Banning {} for {} seconds with reason: {}".format(
            clid, config.actions['banTime'], config.actions['reason']
        ))

    if kick:
        ts3conn.clientkick(clid=clid, reasonid=5, reasonmsg=config.actions['reason'])
        config.logger.info("Kicking {} from server with reason: {}".format(
            clid, config.actions['reason']
        ))


def rbl(ip, clid, ts3conn):
    """
    Takes ip and checks it against a list of rbl's. Will parse the responses and determine if
    the ip address should be marked as spam. It will then ban/kick
    :param ip:
    :return true or false:
    """
    searcher = RBLSearch(ip)
    results = searcher.listed
    # delete search_host because fuck it
    del results['SEARCH_HOST']
    # set results to the length for kick/ban
    results = list(filter(lambda x: results[x]['LISTED'], results.keys()))
    numHits = len(results)

    # fix for kicking and shit
    if numHits >= config.actions['rblListedNumber']:
        if config.actions['onMatch'] == 'kick':
            kickban(kick=True, ban=False, clid=clid, ts3conn=ts3conn)
        if config.actions['onMatch'] == 'ban':
            kickban(kick=False, ban=True, clid=clid, ts3conn=ts3conn)


def clienthandler(ts3conn, clid):
    """
    Send client ID's to this function to return a client id, client ip and what ever else I decide is needed.
    Main purpose is to remove the functions from the join handler since it shouldn't do what it does at this time.
    :return list of dict:
    """
    info = ts3conn.clientinfo(clid=clid)
    return info.parsed


# TODO: Move to commands.py (Subject to change) along with anything else that should be in a class?
def joinshandler(ts3conn, event):
    """
    Used to get client information when a client joins the teamspeak
    Should be used in a loop in order to constantly receive information
    :param ts3conn:
    :param event:
    :return:
    """

    if event.parsed[0].get('client_servergroups') == '8':
        clientid = event.parsed[0]['clid']
        clinfo = clienthandler(ts3conn, clientid)
        clientip = clinfo[0]['connection_client_ip']
        config.logger.info("Client {} with id {} connected from {}".format(
                clinfo[0]['client_nickname'], clientid, clinfo[0]['connection_client_ip']
        ))
        rbl(clientip, clientid, ts3conn)


def checkall(ts3conn):
    """
    Used to get client info of all currently connected clients
    :param ts3conn:
    :return:
    """
    resp = ts3conn.clientlist()
    for key, value in enumerate(r['clid'] for r in resp.parsed):
            clienthandler(ts3conn, value)
            config.logger.info("found client of ID {}".format(value))


# TODO: Fix this function so that it returns ts3conn for use with commands also make it a class
def connectionhandler(config):
    """
    main function of the bot.
    Will handle connecting, monitoring, sending information out and reconnecting
    :return:
    """
    with lib.ts3.query.TS3Connection(config.ts3server['serverIP'], config.ts3server['serverPort']) as ts3conn:
        try:
            ts3conn.login(client_login_name=config.ts3server['serverUsername'],
                          client_login_password=config.ts3server['serverPassword'])
            config.logger.debug("sent ts3conn login command")
            ts3conn.use(sid=config.ts3server['serverID'])
            config.logger.debug("sent ts3conn use command")
            ts3conn.clientupdate(client_nickname=config.ts3server['botNick'])
            config.logger.debug("sent ts3conn client update command, nick name changed to {}".format(config.ts3server['botNick']))
        except lib.ts3.query.TS3QueryError as e:
            config.logger.error(e)

        # Check if we are connected to Teamspeak, if we are move channels and log info.
        if ts3conn.is_connected():
            name = ts3conn.whoami()
            ts3conn.clientmove(clid=name[0]['client_id'], cid=config.ts3server['defaultChannel'])
            config.logger.info("Connected to {} as {}".format(config.ts3server['serverIP'], name[0]['client_nickname']))
        else:
            config.logger.info("Not connected to server, see error for more details.")
            ts3conn.close()
            sys.exit()

        # run a check of all currently connected clients
        checkall(ts3conn)

        ts3conn.servernotifyregister(event="server")

        while True:
            ts3conn.send_keepalive()
            try:
                event = ts3conn.wait_for_event(timeout=540)
            except KeyboardInterrupt:
                config.logger.info("Shutting down.")
                ts3conn.close()
                sys.exit()
            except lib.ts3.query.TS3TimeoutError:
                config.logger.info("no events received, passing.")
                pass
            else:
                joinshandler(ts3conn, event)

if __name__ == '__main__':
    # Get config set up
    config = Config("config.yml")
    connectionhandler(config)
