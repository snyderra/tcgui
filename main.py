"""TC web GUI."""

import argparse
import os
import re
import subprocess
import sys

from flask import Flask, redirect, render_template, request, url_for

BANDWIDTH_UNITS = [
    "bit",  # Bits per second
    "kbit",  # Kilobits per second
    "mbit",  # Megabits per second
    "gbit",  # Gigabits per second
    "tbit",  # Terabits per second
    "bps",  # Bytes per second
    "kbps",  # Kilobytes per second
    "mbps",  # Megabytes per second
    "gbps",  # Gigabytes per second
    "tbps",  # Terabytes per second
]

STANDARD_UNIT = "mbit"


app = Flask(__name__)
PATTERN = None
DEV_LIST = None

app.static_folder = "static"


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--ip",
        type=str,
        default=os.environ.get("TCGUI_IP"),
        help="The IP where the server is listening",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=os.environ.get("TCGUI_PORT"),
        help="The port where the server is listening",
    )
    parser.add_argument(
        "--dev",
        type=str,
        nargs="*",
        default=os.environ.get("TCGUI_DEV"),
        help="The interfaces to restrict to",
    )
    parser.add_argument(
        "--regex",
        type=str,
        default=os.environ.get("TCGUI_REGEX"),
        help="A regex to match interfaces",
    )
    parser.add_argument("--debug", action="store_true", help="Run Flask in debug mode")
    return parser.parse_args()


@app.route("/")
def main():
    rules = get_active_rules()
    allrule=rules[0].copy()
    for k in (allrule.keys()):
        v=set([r[k] for r in rules if r[k]])
        if len(v) > 1:
            allrule[k]="various"
    allrule["name"]="all"
    rules.insert(0,allrule)
    return render_template(
        "main.html", rules=rules, units=BANDWIDTH_UNITS, standard_unit=STANDARD_UNIT
    )


@app.route("/do/", methods=["POST"])
def do():
    action=request.form["action"]
    if "Start" == action:
        command = ["systemctl","start","hostapd@*","-all"]
    if "Stop" == action:
        command = ["systemctl","stop","hostapd@*"]
    if "Shutdown" == action:
        command = ["sudo","systemctl","halt"]
    proc = subprocess.Popen(command)
    proc.wait()
    return redirect(url_for("main"))


@app.route("/new_rule/<interface>", methods=["POST"])
def new_rule(interface):
    delay = request.form["Delay"]
    delay_variance = request.form["DelayVariance"]
    loss = request.form["Loss"]
    loss_correlation = request.form["LossCorrelation"]
    duplicate = request.form["Duplicate"]
    reorder = request.form["Reorder"]
    reorder_correlation = request.form["ReorderCorrelation"]
    corrupt = request.form["Corrupt"]
    limit = request.form["Limit"]
    rate = request.form["Rate"]
    rate_unit = request.form["rate_unit"]

    interface = filter_interface_name(interface)
    if interface == "all":
        interfaces=[x['name'] for x in get_active_rules()]
    else:
        interfaces = [interface]

    for i in interfaces:
        # remove old setup
        command = f"tc qdisc del dev {i} root netem"
        command = command.split(" ")
        proc = subprocess.Popen(command)
        proc.wait()

        # apply new setup
        command = f"tc qdisc add dev {i} root netem"
        if rate != "":
            command += f" rate {rate}{rate_unit}"
        if delay != "":
            command += f" delay {delay}ms"
            if delay_variance != "":
                command += f" {delay_variance}ms"
        if loss != "":
            command += f" loss {loss}%"
            if loss_correlation != "":
                command += f" {loss_correlation}%"
        if duplicate != "":
            command += f" duplicate {duplicate}%"
        if reorder != "":
            command += f" reorder {reorder}%"
            if reorder_correlation != "":
                command += f" {reorder_correlation}%"
        if corrupt != "":
            command += f" corrupt {corrupt}%"
        if limit != "":
            command += f" limit {limit}"
        print(command)
        command = command.split(" ")
        proc = subprocess.Popen(command)
        proc.wait()
    return redirect(url_for("main") + "#" + interface)


@app.route("/remove_rule/<interface>", methods=["POST"])
def remove_rule(interface):
    interface = filter_interface_name(interface)
    if interface == "all":
        interfaces=[x['name'] for x in get_active_rules()]
    else:
        interfaces = [interface]

    for i in interfaces:
        # remove old setup
        command = f"tc qdisc del dev {i} root netem"
        command = command.split(" ")
        proc = subprocess.Popen(command)
        proc.wait()
    return redirect(url_for("main") + "#" + interface)


def filter_interface_name(interface):
    return re.sub(r"[^A-Za-z0-9_-]+", "", interface)


def get_active_rules():
    try:
        proc = subprocess.Popen(["tc", "qdisc"], stdout=subprocess.PIPE)
        output = proc.communicate()[0].decode()
        lines = output.split("\n")[:-1]
        rules = []
        dev = set()
        for line in lines:
            arguments = line.split()
            rule = parse_rule(arguments)
            if rule["name"] and rule["name"] not in dev:
                rules.append(rule)
                dev.add(rule["name"])
                rules.sort(key=lambda x: x["name"])
        return rules
    except:
        d="""qdisc netem 8026: dev test1 root refcnt 5 limit 1000 delay 998ms loss 3% rate 41Kbit
qdisc netem 8027: dev test2 root refcnt 5 limit 1000 delay 999ms 999ms loss 2% rate 42Kbit
qdisc netem 8028: dev test3 root refcnt 5 limit 1000 delay 1s 1s loss 1% rate 43Kbit
qdisc mq 0: dev test4 root""".split("\n")
        return list(map(parse_rule,[x.split() for x in d]))


def parse_rule(split_rule):
    # pylint: disable=too-many-branches
    rule = {
        "name": None,
        "rate": None,
        "delay": None,
        "delayVariance": None,
        "loss": None,
        "lossCorrelation": None,
        "duplicate": None,
        "reorder": None,
        "reorderCorrelation": None,
        "corrupt": None,
        "limit": None,
    }
    i = 0
    for argument in split_rule:
        if argument == "dev":
            # Both regex PATTERN and dev name can be given
            # An interface could match the PATTERN and/or
            # be in the interface list
            if PATTERN is None and DEV_LIST is None:
                rule["name"] = split_rule[i + 1]
            if PATTERN:
                if PATTERN.match(split_rule[i + 1]):
                    rule["name"] = split_rule[i + 1]
            if DEV_LIST:
                if split_rule[i + 1] in DEV_LIST:
                    rule["name"] = split_rule[i + 1]
        elif argument == "rate":
            rule["rate"] = split_rule[i + 1].split("Mbit")[0]
        elif argument == "delay":
            rule["delay"] = split_rule[i + 1]
            if "ms" not in rule["delay"]: 
                if '.' in rule["delay"]:
                    rule["delay"]=str(int(float(rule["delay"][:-1])*1000))+'ms'
                else:
                    rule["delay"]=rule["delay"].replace("s","000ms")
            if len(split_rule) > (i + 2) and "s" in split_rule[i + 2] and "loss" not in split_rule[i + 2]:
                rule["delayVariance"] = split_rule[i + 2]
                print(rule["delayVariance"])
                if "ms" not in rule["delayVariance"]: 
                    if '.' in rule["delayVariance"]:
                        rule["delayVariance"]=str(int(float(rule["delayVariance"][:-1])*1000))+'ms'
                    else:
                        rule["delayVariance"]=rule["delayVariance"].replace("s","000ms")
        elif argument == "loss":
            rule["loss"] = split_rule[i + 1]
            if len(split_rule) > (i + 2) and "%" in split_rule[i + 2]:
                rule["lossCorrelation"] = split_rule[i + 2]
        elif argument == "duplicate":
            rule["duplicate"] = split_rule[i + 1]
        elif argument == "reorder":
            rule["reorder"] = split_rule[i + 1]
            if len(split_rule) > (i + 2) and "%" in split_rule[i + 2]:
                rule["reorderCorrelation"] = split_rule[i + 2]
        elif argument == "corrupt":
            rule["corrupt"] = split_rule[i + 1]
        elif argument == "limit":
            rule["limit"] = split_rule[i + 1]
        i += 1
    return rule


if __name__ == "__main__":
    if os.geteuid() != 0:
        print(
            "You need to have root privileges to run this script.\n"
            "Please try again, this time using 'sudo'. Exiting."
        )
        sys.exit(1)

    # TC Variables
    args = parse_arguments()

    PATTERN = re.compile(args.regex) if args.regex else args.regex
    DEV_LIST = args.dev

    # Flask Variable
    app_args = {"host": args.ip, "port": args.port}
    if not args.debug:
        app_args["debug"] = False
    app.debug = True
    app.run(**app_args)
