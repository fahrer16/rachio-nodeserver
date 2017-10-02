# Rachio-polyglot
This is the Rachio Node Server for the ISY Polyglot interface.  
(c) fahrer16 aka Brian Feeney.  
MIT license. 

I built this on Ubuntu 17.04 for ISY version 5.0.10 and polyglot version 0.0.7 from https://github.com/UniversalDevicesInc/Polyglot

I would like to acknowledge Einstein42's lifx-nodeserver (https://github.com/Einstein42/lifx-nodeserver), which was an invaluable reference when building this project.

The Rachio water controller uses a cloud-based API that is documented here: https://rachio.readme.io/docs/getting-started.
This node server currently implements the Person, Device, and Zone leaves of the Rachio api.


# Installation Instructions:
Same as most other ISY node servers:

1. Backup ISY (just in case)
2. Clone the Rachio Node Server into the /config/node_servers folder of your Polyglot installation:
  * `cd Polyglot/config/node_servers
  * `git clone https://github.com/fahrer16/Rachio-nodeserver.git
3. Add Node Server into Polyglot instance.
  * Log into polyglot web page (http://ip:8080)
  * Select "Add Node Server" and select the following options:
    * Node Server Type: Rachio
    * Name: Up to you, I've only used "Rachio"
    * Node Server ID: Any available slot on the ISY Node Servers/Configure menu from the administration console
  * Click "ADD" and the new node server should appear on the left and hopefully say "Running" under it
  * Open the new node server by clicking on it
  * Copy the "Base URL" and download the profile for the next step
4. Add Node Server into ISY:
  * Log into the ISY admin console and navigate to "Network Connections" on the empty node server slot you entered into Polyglot earlier:
    * Profile Name: Again, up to you, but it's easiest to keep track if it's the same name entered for the node server in Polyglot
    * User ID / Password: Polyglot credentials
    * Base URL: Paste Base URL copied earlier from Polyglot node server web page
    * Host Name: Host Name (or IP address) of your Polyglot server
    * Port: Default is 8080
  * Upload the profile downloaded from the Polyglot node server web page earlier
5. Click "Ok" and reboot the ISY (Configuration tab then "Reboot")
6. Once the ISY is back up upload the profile again in the node server network configuration and reboot the ISY again (quirk of the ISY according to others' node installation instructions)
7. Log back into the ISY admin console.  If your new nodes aren't present, "Add All Nodes" from the new node server from the "Node Servers" menu.

Any Rachio units associated with the specified API key should now show up in the ISY, hit "Query" if the status fields are empty.  
 
  