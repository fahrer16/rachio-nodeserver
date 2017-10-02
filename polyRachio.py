#!/usr/bin/python
""" Rachio Node Server for Polyglot by B. Feeney (fahrer@gmail.com).  
    Based on LIFX Node Server for Polyglot by Einstein.42(James Milne) (https://github.com/Einstein42/lifx-nodeserver) 
    Uses the rachiopy Python client written by rfverbruggen(Robert Verbruggen) (https://github.com/rfverbruggen/rachiopy)"""

from polyglot.nodeserver_api import NodeServer, SimpleNodeServer, Node
from polyglot.nodeserver_api import PolyglotConnector
from polyRachio_types import RachioControl
import os, yaml

VERSION = "0.0.1"

class RachioNodeServer(SimpleNodeServer):
    """ Rachio Node Server """
    link = []
    controllers = []
    zones = []
    schedules = []
    flexschedules = []
    # notifications = [] #TODO: See if notifications should be added.  Maybe there's a way to have an update triggered automatically based on an event from Rachio rather than having to wait for polling?

    def setup(self):
        self.logger = self.poly.logger
        manifest = self.config.get('manifest', {})
        self.get_config()
        self.link = RachioControl(self, 'rachio', 'Rachio Bridge', True, manifest)
        self.link.discover(self.api_key)
        self.update_config()

    def get_config(self):
        """
        Read the sandbox/config.yaml file.
        If it does not exist, create a blank template
        This routine was adapted from jimboca's camera-polyglot project: https://github.com/jimboca/camera-polyglot/blob/master/camera.py
        """
        # The config file.
        self.config_file = self.poly.sandbox + "/config.yaml"
        # Default configuration paramaters.
        default_config = dict(
            api_key = 'API KEY'
        )
        if not os.path.isfile(self.config_file):
            with open(self.config_file, 'w') as outfile:
                outfile.write( yaml.dump(default_config, default_flow_style=False) )
                msg = 'Created default config file, please edit and set the proper values "%s"' % (self.config_file)
                self.logger.error(msg)
                raise IOError(msg)
        try:
            config_h = open(self.config_file, 'r')
        except IOError as e:
            # Does not exist OR no read permissions, so show error in both logs.
            msg = 'Error Unable to open config file "%s"' % (self.config_file)
            self.logger.error(msg)
            raise IOError(msg)
        self.api_config = yaml.load(config_h)
        config_h.close
        # Check that api key is defined.
        if not 'api_key' in self.api_config:
            self.logger.error("api key not defined in %s", self.config_file)
            raise ValueError('Error in config file "%s", see log "%s"' % (self.config_file, self.poly.log_filename))
        else:
            self.api_key = self.api_config['api_key']
            return True

    def poll(self):
        if len(self.controllers) >= 1:
            for i in self.controllers:
                i.update_info(force=False) #only reports currently tracked values without querying the device
        if len(self.zones) >= 1:
            for i in self.zones:
                i.update_info(force=False) #only reports currently tracked values without querying the device
        if len(self.schedules) >= 1:
            for i in self.schedules:
                i.update_info(force=False) #only reports currently tracked values without querying the device
        if len(self.flexschedules) >= 1:
            for i in self.flexschedules:
                i.update_info(force=False) #only reports currently tracked values without querying the device

    def long_poll(self):
        if len(self.controllers) >= 1:
            for i in self.controllers:
                i.update_info(force=True) #queries the device then reports the updated values
        if len(self.zones) >= 1:
            for i in self.zones:
                i.update_info(force=True) #only reports currently tracked values without querying the device
        if len(self.schedules) >= 1:
            for i in self.schedules:
                i.update_info(force=True) #only reports currently tracked values without querying the device
        if len(self.flexschedules) >= 1:
            for i in self.flexschedules:
                i.update_info(force=True) #only reports currently tracked values without querying the device

    def report_drivers(self):
        if len(self.controllers) >= 1:
            for i in self.controllers:
                i.report_driver()
        if len(self.zones) >= 1:
            for i in self.zones:
                i.report_driver()
        if len(self.schedules) >= 1:
            for i in self.schedules:
                i.report_driver()
        if len(self.flexschedules) >= 1:
            for i in self.flexschedules:
                i.report_driver()

def main():
    # Setup connection, node server, and nodes
    poly = PolyglotConnector()
    # Override shortpoll and longpoll timers to 30 seconds and 300 seconds respectively
    # TODO: Look into the possibly of adjusting these times dynamically based on whether or not a schedule is running (i.e. run more frequently if watering)  Or is it possible to add these to bridge node and adjust from ISY?
    nserver = RachioNodeServer(poly, 30, 300)
    poly.connect()
    poly.wait_for_config()
    poly.logger.info("Rachio Node Server Interface version " + VERSION + " created. Initiating setup.")
    nserver.setup()
    poly.logger.info("Setup completed. Running Server.")
    nserver.run()

if __name__ == "__main__":
    main()
