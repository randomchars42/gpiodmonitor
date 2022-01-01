#/usr/bin/env bash

script_dir=$(cd $(dirname "${BASH_SOURCE[0]}") && pwd)
PYTHONPATH=$PYTHONPATH:"$script_dir"/src python3 -m gpiodmonitor.gpiodmonitor "$@"
