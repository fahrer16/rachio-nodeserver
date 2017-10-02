from polyglot.nodeserver_api import Node
import errno
from socket import error as socket_error
from copy import deepcopy
import json, time
try:
    from rachiopy import Rachio
except ImportError, e:
    self.logger.error("rachiopy does not appear to be installed.  Run ""pip install rachiopy"" from a command line. %s", str(e))
 

class RachioControl(Node):
    
    def __init__(self, *args, **kwargs):
        super(RachioControl, self).__init__(*args, **kwargs)

    def discover(self,api_key=None, **kwargs):
        manifest = self.parent.config.get('manifest', {})
        if api_key is not None: RachioControl.api_key = api_key
        try:
            RachioControl.r_api = Rachio(RachioControl.api_key)
            _person_id = RachioControl.r_api.person.getInfo()
            RachioControl.person_id = _person_id[1]['id']
            self.person = RachioControl.r_api.person.get(RachioControl.person_id) #returns json containing all info associated with person (devices, zones, schedules, flex schedules, and notifications)
        except Exception, ex:
            self.logger.error('Connection Error on RachioControl discovery, may be temporary. %s', str(ex))
            return False

        #get devices
        _devices = self.person[1]['devices']
        self.logger.info('%i Rachio controllers found. Adding to ISY', len(_devices))
        for d in _devices:
            _device_id =  str(d['id'])
            _name = str(d['name'])
            _address = str(d['macAddress']).lower()
            lnode = self.parent.get_node(_address)
            if not lnode:
                self.logger.info('Adding new Rachio Controller: %s(%s)', _name, _address)
                self.parent.controllers.append(RachioController(self.parent, _address, _name, d, manifest))
            
            _zones = d['zones']
            self.logger.info('%i Rachio zones found on ""%s"" controller. Adding to ISY', len(_zones), _name)
            for z in _zones:
                _zone_id = str(z['id'])
                _zone_num = str(z['zoneNumber'])
                _zone_addr = _address + _zone_num #construct address for this zone (mac address of controller appended with zone number) because ISY limit is 14 characters
                _zone_name = str(z['name'])
                znode = self.parent.get_node(_zone_addr)
                if not znode:
                    self.logger.info('Adding new Rachio Zone to %s Controller, %s(%s)',_name, _zone_name, _zone_addr)
                    self.parent.zones.append(RachioZone(self.parent,self.parent.get_node(_address), _zone_addr, _zone_name, _device_id, z, manifest)) 
            
            _schedules = d['scheduleRules']
            self.logger.info('%i Rachio schedules found on ""%s"" controller. Adding to ISY', len(_schedules), _name)
            for s in _schedules:
                _sched_id = str(s['id'])
                _sched_addr = _address + _sched_id[-2:] #construct address for this schedule (mac address of controller appended with last 2 characters of schedule unique id) because ISY limit is 14 characters
                _sched_name = str(s['name'])
                snode = self.parent.get_node(_sched_addr)
                if not snode:
                    self.logger.info('Adding new Rachio Schedule to %s Controller, %s(%s)',_name, _sched_name, _sched_addr)
                    self.parent.schedules.append(RachioSchedule(self.parent, self.parent.get_node(_address), _sched_addr, _sched_name, _device_id, s, manifest))

            _flex_schedules = d['flexScheduleRules']
            self.logger.info('%i Rachio Flex schedules found on ""%s"" controller. Adding to ISY', len(_flex_schedules), _name)
            for f in _flex_schedules:
                _flex_sched_id = str(f['id'])
                _flex_sched_addr = _address + _flex_sched_id[-2:] #construct address for this schedule (mac address of controller appended with last 2 characters of schedule unique id) because ISY limit is 14 characters
                _flex_sched_name = str(f['name'])
                fnode = self.parent.get_node(_flex_sched_addr)
                if not fnode:
                    self.logger.info('Adding new Rachio Flex Schedule to %s Controller, %s(%s)',_name, _flex_sched_name, _flex_sched_addr)
                    self.parent.flexschedules.append(RachioFlexSchedule(self.parent, self.parent.get_node(_address), _flex_sched_addr, _flex_sched_name, _device_id, f, manifest))
                       
        self.parent.long_poll()
        return True

    def query(self, **kwargs):
        self.parent.report_drivers()
        return True

    _drivers = {}

    _commands = {'DISCOVER': discover}
    
    node_def_id = 'rachio'

class RachioController(Node):
   
    def __init__(self, parent, address, name, device, manifest=None):
        self.device = device
        self.device_id = device['id']
        self.name = name
        self.address = address
        self.label = self.name
        self.rainDelay_minutes_remaining = 0
        self.currentSchedule = []
        self.scheduleItems = []
        self._tries = 0
        super(RachioController, self).__init__(parent, address, name, True, manifest)
        self.query()
        self.runTypes = {0: "NONE",
                              1: "AUTOMATIC",
                              2: "MANUAL",
                              3: "OTHER"}

        self.scheduleTypes = {0: "NONE",
                              1: "FIXED",
                              2: "FLEX",
                              3: "OTHER"}
        
    def update_info(self, force=False): #setting "force" to "true" updates drivers even if the value hasn't changed
        _running = False #initialize variable so that it could be used even if there was not a need to update the running status of the controller
        try:
            #Get latest device info and populate drivers
            _device = RachioControl.r_api.device.get(self.device_id)[1]
            if force: self.device = _device
            
            _currentSchedule = RachioControl.r_api.device.getCurrentSchedule(self.device_id)[1]
            if force or self.currentSchedule == []: self.currentSchedule = _currentSchedule

        except Exception, ex:
            self.logger.error('Connection Error on %s Rachio Controller refreshState. This could mean an issue with internet connectivity or Rachio servers, normally safe to ignore. %s', self.name, str(ex))
            return False
            
        # ST -> Status (whether Rachio is running a schedule or not)
        try:
            if 'status' in _currentSchedule and 'status' in self.currentSchedule:
                if force or (_currentSchedule['status'] <> self.currentSchedule['status']):
                    _running = (str(_currentSchedule['status']) == "PROCESSING")
                    self.set_driver('ST',(0,100)[_running])
            elif 'status' in _currentSchedule: #There was no schedule last time we checked but there is now, update ISY:
                _running = (str(_currentSchedule['status']) == "PROCESSING")
                self.set_driver('ST',(0,100)[_running])
            elif 'status' in self.currentSchedule: #there was a schedule last time but there isn't now, update ISY:
                self.set_driver('ST',0)
            elif force:
                self.set_driver('ST',0)
        except Exception, ex:
            self.logger.error('Error updating current schedule running status on %s Rachio Controller. %s', self.name, str(ex))

        # GV0 -> "Connected"
        try:
            if force or (_device['status'] <> self.device['status']):
                _connected = (_device['status'] == "ONLINE")
                self.set_driver('GV0',_connected)
        except Exception, ex:
            self.set_driver('GV0',False)
            self.logger.error('Error updating connection status on %s Rachio Controller. %s', self.name, str(ex))

        # GV1 -> "Enabled"
        try:
            if force or (_device['on'] <> self.device['on']):
                self.set_driver('GV1',_device['on'])
        except Exception, ex:
            self.set_driver('GV1',False)
            self.logger.error('Error updating status on %s Rachio Controller. %s', self.name, str(ex))

        # GV2 -> "Paused"
        try:
            if force or (_device['paused'] <> self.device['paused']):
                self.set_driver('GV2', _device['paused'])
        except Exception, ex:
            self.logger.error('Error updating paused status on %s Rachio Controller. %s', self.name, str(ex))

        # GV3 -> "Rain Delay Remaining" in Minutes
        try:
            if 'rainDelayExpirationDate' in _device: 
                _current_time = int(time.time())
                _rainDelayExpiration = _device['rainDelayExpirationDate'] / 1000.
                _rainDelay_minutes_remaining = int(max(_rainDelayExpiration - _current_time,0) / 60.)
                if force or (_rainDelay_minutes_remaining <> self.rainDelay_minutes_remaining):
                    self.set_driver('GV3', _rainDelay_minutes_remaining)
                    self.rainDelay_minutes_remaining = _rainDelay_minutes_remaining
            elif force: self.set_driver('GV3', 0)
        except Exception, ex:
            self.logger.error('Error updating remaining rain delay duration on %s Rachio Controller. %s', self.name, str(ex))
        
        # GV10 -> Active Run Type
        try:
            if 'type' in _currentSchedule: # True when a schedule is running
                _runType = _currentSchedule['type']
                _runVal = 3 #default to "OTHER"
                for key in self.runTypes:
                    if self.runTypes[key].lower() == _runType.lower():
                        _runVal = key
                        break
                self.set_driver('GV10', _runVal)
            else: 
                self.set_driver('GV10', 0, report=force)
        except Exception, ex:
            self.logger.error('Error updating active run type on %s Rachio Controller. %s', self.name, str(ex))

        # GV4 -> Active Zone #
        if 'zoneId' in _currentSchedule and  'zoneId' in self.currentSchedule:
            if force or (_currentSchedule['zoneId'] <> self.currentSchedule['zoneId']):
                try:
                    _active_zone = RachioControl.r_api.zone.get(_currentSchedule['zoneId'])[1]
                    self.set_driver('GV4',_active_zone['zoneNumber'])
                except Exception, ex:
                    self.logger.error('Error updating active zone on %s Rachio Controller. %s', self.name, str(ex))
        elif 'zoneId' in self.currentSchedule: #there was a zone but now there's not, that must mean we're no longer watering and there's therefore no current zone #
            self.set_driver('GV4',0)
        elif 'zoneId' in _currentSchedule: #there's a zone now but there wasn't before, we can try to find the new zone #
            try:
                _active_zone = RachioControl.r_api.zone.get(_currentSchedule['zoneId'])[1]
                self.set_driver('GV4',_active_zone['zoneNumber'])
            except Exception, ex:
                self.logger.error('Error updating new zone on %s Rachio Controller. %s', self.name, str(ex))
        else: #no schedule running:
            if force: self.set_driver('GV4',0)
        
        # GV5 -> Active Schedule remaining minutes and GV6 -> Active Schedule minutes elapsed
        try:
            if 'startDate' in _currentSchedule and 'duration' in _currentSchedule:
                _current_time = int(time.time())
                _start_time = int(_currentSchedule['startDate'] / 1000)
                _duration = int(_currentSchedule['duration'])

                _seconds_elapsed = max(_current_time - _start_time,0)
                _minutes_elapsed = round(_seconds_elapsed / 60. ,1)
                
                _seconds_remaining = max(_duration - _seconds_elapsed,0)
                _minutes_remaining = round(_seconds_remaining / 60. ,1)

                self.set_driver('GV5',_minutes_remaining)
                self.set_driver('GV6',_minutes_elapsed)
                #self.logger.info('%f minutes elapsed and %f minutes remaining on %s Rachio Controller. %s', _minutes_elapsed, _minutes_remaining, self.name)
            else: 
                self.set_driver('GV5',0.0)
                self.set_driver('GV6',0.0)
        except Exception, ex:
            self.logger.error('Error trying to retrieve active schedule minutes remaining/elapsed on %s Rachio Controller. %s', self.name, str(ex))

        # GV7 -> Cycling (true/false)
        try:
            if 'cycling' in _currentSchedule and 'cycling' in self.currentSchedule:
                if force or (_currentSchedule['cycling'] <> self.currentSchedule['cycling']):
                    self.set_driver('GV7',_currentSchedule['cycling'])
            elif 'cycling' in _currentSchedule: #there's a schedule running now, but there wasn't last time we checked, update the ISY:
                self.set_driver('GV7',_currentSchedule['cycling'])
            elif force: self.set_driver('GV7', False) #no schedule active
        except Exception, ex:
            self.logger.error('Error trying to retrieve cycling status on %s Rachio Controller. %s', self.name, str(ex))
        
        # GV8 -> Cycle Count
        try:
            if 'cycleCount' in _currentSchedule and 'cycleCount' in self.currentSchedule:
                if force or (_currentSchedule['cycleCount'] <> self.currentSchedule['cycleCount']):
                    self.set_driver('GV8',_currentSchedule['cycleCount'])
            elif 'cycleCount' in _currentSchedule: #there's a schedule running now, but there wasn't last time we checked, update the ISY:
                self.set_driver('GV8',_currentSchedule['cycleCount'])
            elif force: self.set_driver('GV8',0) #no schedule active
        except Exception, ex:
            self.logger.error('Error trying to retrieve cycle count on %s Rachio Controller. %s', self.name, str(ex))

        # GV9 -> Total Cycle Count
        try:
            if 'totalCycleCount' in _currentSchedule and 'totalCycleCount' in self.currentSchedule:
                if force or (_currentSchedule['totalCycleCount'] <> self.currentSchedule['totalCycleCount']):
                    self.set_driver('GV9',_currentSchedule['totalCycleCount'])
            elif 'totalCycleCount' in _currentSchedule: #there's a schedule running now, but there wasn't last time we checked, update the ISY:
                self.set_driver('GV9',_currentSchedule['totalCycleCount'])
            elif force: self.set_driver('GV9',0) #no schedule active
        except Exception, ex:
            self.logger.error('Error trying to retrieve total cycle count on %s Rachio Controller. %s', self.name, str(ex))

        # GV11 -> Minutes until next automatic schedule start
        # GV12 -> Type of next schedule (FLEX, or FIXED)
        try:
            _scheduleItems = RachioControl.r_api.device.getScheduleItem(self.device_id)[1]
            if force or self.scheduleItems == []: self.scheduleItems = _scheduleItems
            if len(_scheduleItems) > 0:
                _current_time = int(time.time())
                _next_start_time = int(_scheduleItems[0]['absoluteStartDate'] / 1000.) #TODO: Looks like earliest schedule is always in the 0th element, but might need to actually loop through and check.
                _seconds_remaining = max(_next_start_time - _current_time,0)
                _minutes_remaining = round(_seconds_remaining / 60. ,1)
                self.set_driver('GV11',_minutes_remaining)

                _scheduleType = _scheduleItems[0]['scheduleType']
                _scheduleVal = 3 #default to "OTHER" in case an unexpected item is returned (API documentation does not include exhaustive list of possibilities)
                for key in self.scheduleTypes:
                    if self.scheduleTypes[key].lower() == _scheduleType.lower():
                        _scheduleVal = key
                        break
                self.set_driver('GV12',_scheduleVal)
            elif force: 
                self.set_driver('GV11',0.0)
                self.set_driver('GV12',0)
        except Exception, ex:
            self.logger.error('Error trying to retrieve minutes remaining/type of next planned schedule on %s Rachio Controller. %s', self.name, str(ex))
        
        self.device = _device
        self.currentSchedule = _currentSchedule
        self.report_driver()
        return True
        
    def query(self, **kwargs):
        self.logger.info('query command received on %s Rachio Controller.', self.name)
        self.update_info(force=True)
        return True

    def _st(self, **kwargs):
        self.update_info(force=True)
        return True

    def enable(self, **kwargs): #Enables Rachio (schedules, weather intelligence, water budget, etc...)
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                RachioControl.r_api.device.on(self.device_id)
                self.update_info(force=False) #update info but don't force updates to ISY if values haven't changed.
                self.logger.info('Command received to enable %s Controller',self.name)
                self._tries = 0
                return True
            except Exception, ex:
                self.logger.error('Error turning on %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False
        
    def disable(self, **kwargs): #Disables Rachio (schedules, weather intelligence, water budget, etc...)
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                RachioControl.r_api.device.off(self.device_id)
                self.update_info(force=False) #update info but don't force updates to ISY if values haven't changed.
                self.logger.info('Command received to disable %s Controller',self.name)
                self._tries = 0
                return True
            except Exception, ex:
                self.logger.error('Error turning off %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False

    def _apply(self, **kwargs):
        self.logger.info('Received apply command: %s', str(kwargs))
        return True
    
    def stop(self, **kwargs):
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                RachioControl.r_api.device.stopWater(self.device_id)
                self.logger.info('Command received to stop watering on %s Controller',self.name)
                self.update_info(force=False) #update info but don't force updates to ISY if values haven't changed.
                self._tries = 0
                return True
            except Exception, ex:
                self.logger.error('Error stopping watering on %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False
    
    def rainDelay(self, **kwargs):
        _minutes = kwargs.get('value')
        if _minutes is None:
            self.logger.error('Rain Delay requested on %s Rachio Controller but no duration specified', self.name)
            return False
        else:
            self._tries = 0
            while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
                try:
                    _seconds = int(_minutes * 60.)
                    RachioControl.r_api.device.rainDelay(self.device_id, _seconds)
                    self.update_info(force=False) #update info but don't force updates to ISY if values haven't changed.
                    self.logger.info('Received rain Delay command on %s Rachio Controller for %s minutes', self.name, str(_minutes))
                    self._tries = 0
                    return True
                except Exception, ex:
                    self.logger.error('Error setting rain delay on %s Rachio Controller to _seconds %i (%s)', self.name, _seconds, str(ex))
                    self._tries = self._tries +1
            return False

    #Status (on/off) ST, Connected GV0, Enabled GV1, Paused GV2, Rain Delay Minutes Remaining GV3, Active Zone # GV4, Active Schedule Minutes Remaining GV5, Active Schedule Minutes Elapsed GV6, cycling GV7, cycle count GV8, total cycle count GV9, current schedule Type GV10
    _drivers = {'ST': [0, 78, int], 'GV0': [0, 2, int], 'GV1': [0, 2, int], 'GV2': [0, 2, int], 'GV3': [0, 45, int],
                'GV4': [0, 56, int], 'GV5': [0, 45, float], 'GV6': [0, 45, float], 'GV7': [0, 2, int], 'GV8': [0, 56, int], 
                'GV9': [0, 56, int], 'GV10': [0,25, int], 'GV11': [0,45, float], 'GV12': [0,25, int]}

    _commands = {'DON': enable, 'DOF': disable, 'ST': _st, 'QUERY': query, 'STOP': stop,
                 'APPLY': _apply, 'RAIN_DELAY': rainDelay}

    node_def_id = 'rachio_device'


class RachioZone(Node):  
    def __init__(self, parent, primary, address, name, device_id, zone, manifest=None):
        self.device_id = device_id
        self.zone = zone
        self.zone_id = zone['id']
        self.name = name
        self.address = address
        self.label = self.name
        self.rainDelayExpiration = 0
        self.currentSchedule = []
        super(RachioZone, self).__init__(parent, address, name, primary, manifest)
        self._tries = 0
        self.query()
        
    def update_info(self, force=False): #setting "force" to "true" updates drivers even if the value hasn't changed
        _running = False #initialize variable so that it could be used even if there was not a need to update the running status of the zone
        try:
            #Get latest zone info and populate drivers
            _zone = RachioControl.r_api.zone.get(self.zone_id)[1]
            if force: self.zpme = _zone
            _currentSchedule = RachioControl.r_api.device.getCurrentSchedule(self.device_id)[1]
            if self.currentSchedule == []: self.currentSchedule = _currentSchedule
        except Exception, ex:
            self.logger.error('Connection Error on %s Rachio zone. This could mean an issue with internet connectivity or Rachio servers, normally safe to ignore. %s', self.name, str(ex))
            return False
            
        # ST -> Status (whether Rachio zone is running a schedule or not)
        try:
            if 'status' in _currentSchedule and 'zoneId' in _currentSchedule and 'status' in self.currentSchedule and 'zoneId' in self.currentSchedule:
                if force or (_currentSchedule['status'] <> self.currentSchedule['status']) or (_currentSchedule['zoneId'] <> self.currentSchedule['zoneId']):
                    _running = (str(_currentSchedule['status']) == "PROCESSING") and (_currentSchedule['zoneId'] == self.zone_id)
                    self.set_driver('ST',(0,100)[_running])
            elif 'status' in _currentSchedule and 'zoneId' in _currentSchedule: #there's a schedule running now, but there wasn't last time we checked, update the ISY:
                _running = (str(_currentSchedule['status']) == "PROCESSING") and (_currentSchedule['zoneId'] == self.zone_id)
                self.set_driver('ST',(0,100)[_running])
            elif 'status' in self.currentSchedule and 'zoneId' in self.currentSchedule: #schedule stopped running since last time, update the ISY:
                self.set_driver('ST',0)
            elif force:
                self.set_driver('ST',0)
        except Exception, ex:
            self.logger.error('Error updating current schedule running status on %s Rachio Zone. %s', self.name, str(ex))

        # GV0 -> "Enabled"
        try:
            if force or (_zone['enabled'] <> self.zone['enabled']):
                self.set_driver('GV0',_zone['enabled'])
        except Exception, ex:
            self.set_driver('GV0',False)
            self.logger.error('Error updating enable status on %s Rachio Zone. %s', self.name, str(ex))

        # GV1 -> "Zone Number"
        try:
            if force or (_zone['zoneNumber'] <> self.zone['zoneNumber']):
                self.set_driver('GV1', _zone['zoneNumber'])
        except Exception, ex:
            self.logger.error('Error updating zone number on %s Rachio Zone. %s', self.name, str(ex))

        # GV2 -> Available Water
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            if force or (_zone['availableWater'] <> self.zone['availableWater']):
                self.set_driver('GV2', _zone['availableWater'])
        except Exception, ex:
            self.logger.error('Error updating available water on %s Rachio Zone. %s', self.name, str(ex))

        # GV3 -> root zone depth
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            if force or (_zone['rootZoneDepth'] <> self.zone['rootZoneDepth']):
                self.set_driver('GV3', _zone['rootZoneDepth'])
        except Exception, ex:
            self.logger.error('Error updating root zone depth on %s Rachio Zone. %s', self.name, str(ex))

		# GV4 -> allowed depletion
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            if force or (_zone['managementAllowedDepletion'] <> self.zone['managementAllowedDepletion']):
                self.set_driver('GV4', _zone['managementAllowedDepletion'])
        except Exception, ex:
            self.logger.error('Error updating allowed depletion on %s Rachio Zone. %s', self.name, str(ex))

		# GV5 -> efficiency
        try:
            if force or (_zone['efficiency'] <> self.zone['efficiency']):
                self.set_driver('GV5', int(_zone['efficiency'] * 100.))
        except Exception, ex:
            self.logger.error('Error updating efficiency on %s Rachio Zone. %s', self.name, str(ex))

		# GV6 -> square feet
        # TODO: This is in square feet, but there's no unit available in the ISY for square feet.  Update if UDI makes it available
        try:
            if force or (_zone['yardAreaSquareFeet'] <> self.zone['yardAreaSquareFeet']):
                self.set_driver('GV6', _zone['yardAreaSquareFeet'])
        except Exception, ex:
            self.logger.error('Error updating square footage on %s Rachio Zone. %s', self.name, str(ex))

		# GV7 -> irrigation amount
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            if 'irrigationAmount' in _zone and 'irrigationAmount' in self.zone['irrigationAmount']:
                if force or (_zone['irrigationAmount'] <> self.zone['irrigationAmount']):
                    self.set_driver('GV7', _zone['irrigationAmount'])
            else:
                if force: self.set_driver('GV7', 0)
        except Exception, ex:
            self.logger.error('Error updating irrigation amount on %s Rachio Zone. %s', self.name, str(ex))

		# GV8 -> depth of water
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            if force or (_zone['depthOfWater'] <> self.zone['depthOfWater']):
                self.set_driver('GV8', _zone['depthOfWater'])
        except Exception, ex:
            self.logger.error('Error updating depth of water on %s Rachio Zone. %s', self.name, str(ex))

		# GV9 -> runtime
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            if force or (_zone['runtime'] <> self.zone['runtime']):
                self.set_driver('GV9', _zone['runtime'])
        except Exception, ex:
            self.logger.error('Error updating runtime on %s Rachio Zone. %s', self.name, str(ex))

		# GV10 -> inches per hour
        try:
            if force or (_zone['customNozzle']['inchesPerHour'] <> self.zone['customNozzle']['inchesPerHour']):
                self.set_driver('GV10', _zone['customNozzle']['inchesPerHour'])
        except Exception, ex:
            self.logger.error('Error updating inches per hour on %s Rachio Zone. %s', self.name, str(ex))
        
        self.zone = _zone
        self.currentSchedule = _currentSchedule
        self.report_driver()
        return True
        
    def query(self, **kwargs):
        self.logger.info('query command received on %s Rachio Zone', self.name)
        self.update_info(force=True)
        return True

    def _st(self, **kwargs):
        self.update_info(force=True)
        return True

    
    def _apply(self, **kwargs):
        self.logger.info('Received apply command: %s', str(kwargs))
        return True
    
    def start(self, **kwargs):
        _minutes = kwargs.get('value')
        if _minutes is None:
            self.logger.error('Zone %s requested to start but no duration specified', self.name)
            return False
        else:
            self._tries = 0
            while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
                try:
                    if _minutes == 0:
                        self.logger.error('Zone %s requested to start but duration specified was zero', self.name)
                        return False
                    _seconds = int(_minutes * 60.)
                    RachioControl.r_api.zone.start(self.zone_id, _seconds)
                    self.logger.info('Command received to start watering zone %s for %i minutes',self.name, _minutes)
                    self.update_info(force=False) #update info but don't force updates to ISY if values haven't changed.
                    self._tries = 0
                    return True
                except Exception, ex:
                    self.logger.error('Error starting watering on zone %s. %s', self.name, str(ex))
                    self._tries = self._tries + 1
            return False
       
    
    #status(running) ST, enabled GV0, zone number GV1, available water GV2, root zone depth GV3, allowed depletion GV4, efficiency GV5, square feet GV6, irrigation amount GV7, depth of water GV8, runtime GV9, inches per hour GV10
    _drivers = {'ST': [0, 78, int], 'GV0': [0, 2, int], 'GV1': [0, 56, int], 'GV2': [0, 105, float], 'GV3': [0, 105, float],
                'GV4': [0, 105, float], 'GV5': [0, 51, int], 'GV6': [0, 18, int], 'GV7': [0, 105, float], 'GV8': [0, 105, float], 'GV9': [0, 45, int], 'GV10': [0,24,float]} 

    _commands = {'ST': _st, 'QUERY': query, 'START': start,
                 'APPLY': _apply}

    node_def_id = 'rachio_zone'


class RachioSchedule(Node):  
    def __init__(self, parent, primary, address, name, device_id, schedule, manifest=None):
        self.device_id = device_id
        self.schedule = schedule
        self.schedule_id = schedule['id']
        self.name = name
        self.address = address
        self.label = self.name
        self.currentSchedule = []
        self._tries = 0
        super(RachioSchedule, self).__init__(parent, address, name, primary, manifest)
        self.query()
        
    def update_info(self, force=False): #setting "force" to "true" updates drivers even if the value hasn't changed
        _running = False #initialize variable so that it could be used even if there was not a need to update the running status of the schedule
        try:
            #Get latest schedule info and populate drivers
            _schedule = RachioControl.r_api.schedulerule.get(self.schedule_id)[1]
            if force: self.schedule = _schedule
            _currentSchedule = RachioControl.r_api.device.getCurrentSchedule(self.device_id)[1]
            if self.currentSchedule == []: self.currentSchedule = _currentSchedule
        except Exception, ex:
            self.logger.error('Connection Error on %s Rachio schedule. This could mean an issue with internet connectivity or Rachio servers, normally safe to ignore. %s', self.name, str(ex))
            return False
            
        # ST -> Status (whether Rachio schedule is running a schedule or not)
        try:
            if 'scheduleRuleId' in _currentSchedule and 'scheduleRuleId' in self.currentSchedule:
                if force or (_currentSchedule['scheduleRuleId'] <> self.currentSchedule['scheduleRuleId']):
                    _running = (_currentSchedule['scheduleRuleId'] == self.schedule_id)
                    self.set_driver('ST',(0,100)[_running])
            elif 'scheduleRuleId' in _currentSchedule: #There was no schedule last time we checked but there is now, update ISY:
                _running = (str(_currentSchedule['scheduleRuleId']) == self.schedule_id)
                self.set_driver('ST',(0,100)[_running])
            elif 'scheduleRuleId' in self.currentSchedule: #there was a schedule last time but there isn't now, update ISY:
                self.set_driver('ST',0)
            elif force:
                self.set_driver('ST',0)
        except Exception, ex:
            self.logger.error('Error updating current schedule running status on %s Rachio Schedule. %s', self.name, str(ex))

        # GV0 -> "Enabled"
        try:
            if force or (_schedule['enabled'] <> self.schedule['enabled']):
                self.set_driver('GV0',_schedule['enabled'])
        except Exception, ex:
            self.logger.error('Error updating enable status on %s Rachio Schedule. %s', self.name, str(ex))

        # GV1 -> "rainDelay" status
        try:
            if force or (_schedule['rainDelay'] <> self.schedule['rainDelay']):
                self.set_driver('GV1',_schedule['rainDelay'])
        except Exception, ex:
            self.logger.error('Error updating schedule rain delay on %s Rachio Schedule. %s', self.name, str(ex))

        # GV2 -> duration (minutes)
        try:
            if force or (_schedule['totalDuration'] <> self.schedule['totalDuration']):
                self.set_driver('GV2', _schedule['totalDuration'])
        except Exception, ex:
            self.logger.error('Error updating total duration on %s Rachio Schedule. %s', self.name, str(ex))

        # GV3 -> seasonal adjustment
        try:
            if force or (_schedule['seasonalAdjustment'] <> self.schedule['seasonalAdjustment']):
                _seasonalAdjustment = _schedule['seasonalAdjustment'] * 100
                self.set_driver('GV3', _seasonalAdjustment)
        except Exception, ex:
            self.logger.error('Error updating seasonal adjustment on %s Rachio Schedule. %s', self.name, str(ex))

        # GV4 -> Minutes until next automatic schedule start
        try:
            _scheduleItems = RachioControl.r_api.device.getScheduleItem(self.device_id)[1]
            if force or self.scheduleItems == []: self.scheduleItems = _scheduleItems
            if len(_scheduleItems) > 0:
                _current_time = int(time.time())
                _next_start_time = 0
                for _item in _scheduleItems: #find the lowest planned start time for this schedule:
                    if _item['scheduleRuleId'] == self.schedule_id:
                        if _next_start_time == 0 or _item['absoluteStartDate'] < _next_start_time:
                            _next_start_time = _item['absoluteStartDate']
                
                _next_start_time = int(_next_start_time / 1000.)
                _seconds_remaining = max(_next_start_time - _current_time,0)
                _minutes_remaining = round(_seconds_remaining / 60. ,1)
                self.set_driver('GV4',_minutes_remaining)

            elif force: 
                self.set_driver('GV4',0.0)
        except Exception, ex:
            self.logger.error('Error trying to retrieve minutes remaining until next run of %s Rachio Schedule. %s', self.name, str(ex))

        self.schedule = _schedule
        self.currentSchedule = _currentSchedule
        self.report_driver()
        return True
        
    def query(self, **kwargs):
        self.logger.info('query command received on %s Rachio Schedule.', self.name)
        self.update_info(force=True)
        return True

    def _st(self, **kwargs):
        self.update_info(force=True)
        return True

    
    def _apply(self, **kwargs):
        self.logger.info('Received apply command: %s', str(kwargs))
        return True
    
    def start(self, **kwargs):
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                RachioControl.r_api.schedulerule.start(self.schedule_id)
                self.logger.info('Command received to start watering schedule %s',self.name)
                self.update_info(force=False) #update info but don't force updates to ISY if values haven't changed.
                self._tries = 0
                return True
            except Exception, ex:
                self.logger.error('Error starting watering on schedule %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False
    
    def skip(self, **kwargs):
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                RachioControl.r_api.schedulerule.skip(self.schedule_id)
                self.logger.info('Command received to skip watering schedule %s',self.name)
                self.update_info(force=False) #update info but don't force updates to ISY if values haven't changed.
                self._tries = 0
                return True
            except Exception, ex:
                self.logger.error('Error skipping watering on schedule %s. %s', self.name, str(ex))
                self._tries = self._tries = 1
        return False

    def seasonalAdjustment(self, **kwargs):
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                _value = kwargs.get('value')
                if _value is not None:
                    _value = _value / 100.
                    RachioControl.r_api.schedulerule.seasonalAdjustment(self.schedule_id, _value)
                    self.logger.info('Command received to change seasonal adjustment on schedule %s to %s',self.name, str(_value))
                    self.update_info(force=False) #update info but don't force updates to ISY if values haven't changed.
                    self._tries = 0
                    return True
                else:
                    self.logger.error('Command received to change seasonal adjustment on schedule %s but no value supplied',self.name)
                    return False
            except Exception, ex:
                self.logger.error('Error changing seasonal adjustment on schedule %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False

    #status(running) ST, enabled GV0, rain delay GV1, duration GV2, seasonal adjustment GV3
    _drivers = {'ST': [0, 78, int], 'GV0': [0, 2, int], 'GV1': [0, 2, int], 'GV2': [0, 45, float], 'GV3': [0, 51, float], 'GV4': [0, 45, float]} 

    _commands = {'ST': _st, 'QUERY': query, 'START': start, 'SKIP': skip, 'ADJUST':seasonalAdjustment,
                 'APPLY': _apply}

    node_def_id = 'rachio_schedule'


class RachioFlexSchedule(Node):
   
    def __init__(self, parent, primary, address, name, device_id, schedule, manifest=None):
        self.device_id = device_id
        self.schedule = schedule
        self.schedule_id = schedule['id']
        self.name = name
        self.address = address
        self.label = self.name
        self.currentSchedule = []
        super(RachioFlexSchedule, self).__init__(parent, address, name, primary, manifest)
        self.query()
        
    def update_info(self, force=False): #setting "force" to "true" updates drivers even if the value hasn't changed
        _running = False #initialize variable so that it could be used even if there was not a need to update the running status of the schedule
        try:
            #Get latest schedule info and populate drivers
            _schedule = RachioControl.r_api.flexschedulerule.get(self.schedule_id)[1]
            if force: self.schedule = _schedule
            _currentSchedule = RachioControl.r_api.device.getCurrentSchedule(self.device_id)[1]
            if self.currentSchedule == []: self.currentSchedule = _currentSchedule
        except Exception, ex:
            self.logger.error('Connection Error on %s Rachio schedule. This could mean an issue with internet connectivity or Rachio servers, normally safe to ignore. %s', self.name, str(ex))
            return False
            
        # ST -> Status (whether Rachio schedule is running a schedule or not)
        try:
            if 'scheduleRuleId' in _currentSchedule and 'scheduleRuleId' in self.currentSchedule:
                if force or (_currentSchedule['scheduleRuleId'] <> self.currentSchedule['scheduleRuleId']):
                    _running = (_currentSchedule['scheduleRuleId'] == self.schedule_id)
                    self.set_driver('ST',(0,100)[_running])
            elif 'scheduleRuleId' in _currentSchedule: #There was no schedule last time we checked but there is now, update ISY:
                _running = (str(_currentSchedule['scheduleRuleId']) == self.schedule_id)
                self.set_driver('ST',(0,100)[_running])
            elif 'scheduleRuleId' in self.currentSchedule: #there was a schedule last time but there isn't now, update ISY:
                self.set_driver('ST',0)
            elif force:
                self.set_driver('ST',0)
        except Exception, ex:
            self.logger.error('Error updating current schedule running status on %s Rachio FlexSchedule. %s', self.name, str(ex))

        # GV0 -> "Enabled"
        try:
            if force or (_schedule['enabled'] <> self.schedule['enabled']):
                self.set_driver('GV0',_schedule['enabled'])
        except Exception, ex:
            self.logger.error('Error updating enable status on %s Rachio FlexSchedule. %s', self.name, str(ex))

        # GV2 -> duration (minutes)
        try:
            if force or (_schedule['totalDuration'] <> self.schedule['totalDuration']):
                _seconds = _schedule['totalDuration']
                _minutes = int(_seconds / 60.)
                self.set_driver('GV2', _minutes)
        except Exception, ex:
            self.logger.error('Error updating total duration on %s Rachio FlexSchedule. %s', self.name, str(ex))

        self.schedule = _schedule
        self.currentSchedule = _currentSchedule
        self.report_driver()
        return True

        # GV4 -> Minutes until next automatic schedule start
        try:
            _scheduleItems = RachioControl.r_api.device.getScheduleItem(self.device_id)[1]
            if force or self.scheduleItems == []: self.scheduleItems = _scheduleItems
            if len(_scheduleItems) > 0:
                _current_time = int(time.time())
                _next_start_time = 0
                for _item in _scheduleItems: #find the lowest planned start time for this schedule:
                    if _item['scheduleRuleId'] == self.schedule_id:
                        if _next_start_time == 0 or _item['absoluteStartDate'] < _next_start_time:
                            _next_start_time = _item['absoluteStartDate']
                
                _next_start_time = int(_next_start_time / 1000.)
                _seconds_remaining = max(_next_start_time - _current_time,0)
                _minutes_remaining = round(_seconds_remaining / 60. ,1)
                self.set_driver('GV4',_minutes_remaining)

            elif force: 
                self.set_driver('GV4',0.0)
        except Exception, ex:
            self.logger.error('Error trying to retrieve minutes remaining until next run of %s Rachio FlexSchedule. %s', self.name, str(ex))
        
    def query(self, **kwargs):
        self.logger.info('query command received on %s Rachio Flex Schedule', self.name)
        self.update_info(force=True)
        return True

    def _st(self, **kwargs):
        self.update_info(force=True)
        return True

    def _apply(self, **kwargs):
        self.logger.info('Received apply command: %s', str(kwargs))
        return True
    
    #status(running) ST, enabled GV0, duration GV2
    _drivers = {'ST': [0, 78, int], 'GV0': [0, 2, int], 'GV2': [0, 45, float], 'GV4': [0, 45, float]} 

    _commands = {'ST': _st, 'QUERY': query, 'APPLY': _apply}

    node_def_id = 'rachio_flexschedule'