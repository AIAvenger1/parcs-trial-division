#!/bin/bash

node_type=$1

master_ip=$2
# PARCS_IP picks the address the node registers with (e.g. its private-network
# address); by default it is the first address of the machine.
self_ip=${PARCS_IP:-`hostname -I | cut -d' ' -f1`}

echo '[Node]'

if [ "$node_type" == "master" ]; then
        echo -e 'master=True\nport=8080'
else
        echo -e "host=${self_ip}\nip=${self_ip}\nmaster=False"
        echo
        echo -e "[Master Node]\nhost=${master_ip}\nip=${master_ip}\nport=8080"
fi
