#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys


class Command:
    """A command executor"""
    
    _command = None
    """The command to execute"""

    _env = None
    """The command environment to set"""

    def __init__(self, command, env={}):
        """Creates a new command executor from the given command"""
        # Preprocess arguments if necessary
        if type(command) is str:
            command = [command]
        
        # Set properties
        self._command = command
        self._env = env
    
    def capture(self, shell=False, trim=True) -> str:
        """Executes the command and captures the output"""
        result = subprocess.check_output(self._command, shell=shell, env={**os.environ, **self._env})
        result = result.decode("utf-8")
        return result.strip() if trim else result

    def display(self, shell=False):
        """Executes the command and displays the output to the shell"""
        result = subprocess.run(self._command, capture_output=False, shell=shell, env={**os.environ, **self._env})
        return result.check_returncode()


class Dialog:
    """Implements some user interacting dialogs"""

    @classmethod
    def truefalse(cls, question: str, true="Yes", false="No", default=False) -> bool:
        """Asks a yes/no or true/false question"""
        command = [
            "dialog", "--stdout", "--clear",
            "--yes-label", true, "--no-label", false, "--default-button", true if default else false,
            "--yesno", question, "0", "0"
        ]
        try:
            Command(command).capture()
            return True
        except:
            return False

    @classmethod
    def input(cls, dialog: str, true="Ok", false="Cancel", default=False) -> str:
        """Asks for user input"""
        command = [
            "dialog", "--stdout", "--clear",
            "--ok-label", true, "--cancel-label", false, "--default-button", true if default else false,
            "--inputbox", dialog, "0", "0"
        ]
        try:
            return Command(command).capture()
        except:
            raise RuntimeError("Action cancelled by user")

    @classmethod
    def info(cls, info: str):
        """Displays some information"""
        command = [
            "dialog", "--stdout",
            "--infobox", info, "0", "0"
        ]
        Command(command).capture()


class Config:
    """The configuration"""

    _config = None
    """The configuration struct"""

    def __init__(self, env_json="RESTIC_EZ_CONFIG", env_file="RESTIC_EZ_CONFIG_FILE", var="CONFIG"):
        """Load the config from an environment variable or global variable"""
        if env_json in os.environ:
            self._config = json.loads(os.environ[env])
        elif env_file in os.environ:
            config_json = open(env_file, mode="r").read()
            self._config = json.loads(config_json)
        elif var in globals():
            self._config = json.loads(globals()[var])
        else:
            raise RuntimeError("No configuration in environment or global namespace")

        # Evaluate command fields
        self._eval_field("restic", "pass")
        self._eval_field("s3", "pass")
    
    def get_directory(self) -> str:
        """Gets the managed directory"""
        return self._config["directory"]
    
    def get_restic_flags(self, context: str) -> list:
        """Gets the restic flags for the given context"""
        if f"flags_{ context }" in self._config["restic"]:
            return self._config["restic"][f"flags_{ context }"]
        else:
            return []

    def env(self) -> dict[str, str]:
        """Generates a shell environment dictionary from the config"""
        return {
            "RESTIC_EZ_CONFIG": json.dumps(self._config),
            "DIRECTORY": self.get_directory(),
            "RESTIC_PASSWORD": self._config["restic"]["pass"],
            "RESTIC_REPOSITORY": self._config["restic"]["repo"],
            "AWS_ACCESS_KEY_ID": self._config["s3"]["user"],
            "AWS_SECRET_ACCESS_KEY": self._config["s3"]["pass"]
        }

    def _eval_field(self, section: str, name: str):
        """Evaluates a dynamic configuration field"""
        if name in self._config[section]:
            return
        elif f"{ name }_command" in self._config[section]:
            value = Command(self._config[section][f"{ name }_command"]).capture(shell=True)
            self._config[section][name] = value
        else:
            self._config[section][name] = Dialog.input(f"Enter value for \"{ section }->{ name }\":")


class Restic:
    """Implements a simple restic API"""

    _config = None
    """The restic config"""

    def __init__(self, config):
        """Creates a new restic instance"""
        self._config = config
    
    def list(self) -> list[str]:
        """Lists all existing archives in a human readable format"""
        archives = []
        for archive in self._list():
            archives.append(f"{ archive['time'] } { archive['id'] } { archive['tags'] }")
        return "\n".join(archives)

    def create(self, tags=[]):
        """Creates a new archive with the given tags"""
        command = [
            "restic", "backup",
            "--tag", ",".join(tags),
            *self._config.get_restic_flags("backup"),
            self._config.get_directory()
        ]
        Command(command, env=self._config.env()).display()
    
    def restore(self, tmpdir: str, id=None):
        """Restores an archive"""
        # Preprocess arguments if necessary
        if id is None:
            archives = self._list()
            archives = filter(lambda a: "snapshot" not in a["tags"], archives)
            archives = sorted(archives, key=lambda a: a["time"])
            id = archives[-1]["id"]
        
        # Restore the archive
        command = [
            "restic", "restore",
            "--target", tmpdir,
            *self._config.get_restic_flags("restore"),
            id
        ]
        Command(command, env=self._config.env()).display()
    
    def check(self):
        """Checks the repository consistency and integrity"""
        command = [
            "restic", "check",
            "--check-unused", "--read-data",
            *self._config.get_restic_flags("check")
        ]
        Command(command, env=self._config.env()).display()
    
    def break_lock(self):
        """Breaks a stale repository lock"""
        command = [
            "restic", "unlock",
            *self._config.get_restic_flags("break_lock")
        ]
        Command(command, env=self._config.env()).display()

    def _list(self) -> list:
        """Gathers raw information about all existing archives"""
        command = [
            "restic", "snapshots",
            "--json",
            *self._config.get_restic_flags("list")
        ]
        result_json = Command(command, env=self._config.env()).capture()
        return json.loads(result_json)


def help(exitcode=0):
    """Prints the help text and exits with `exitcode`"""
    text = "\n".join([
        f"Usage: `{ sys.argv[0] } command` - where command is one of the following:",
        f"",
        f"    list: Lists all archives",
        f"",
        f"    create: Creates a new backup",
        f"",
        f"    restore: Creates a snapshot of the current state and restores the latest backup",
        f"",
        f"    check: Checks the repository consistency and integrity",
        f"",
        f"    break-lock: Breaks a stale repository lock",
        f"",
        f"    shell: Starts a subshell with the configuration exported as environment",
        f"",
        f"    help: Displays this help"
    ])
    print(text)
    sys.exit(exitcode)


def list():
    """Lists all archives"""
    config = Config()
    Dialog.info("Listing archives...")
    archives = Restic(config).list()
    print(archives)


def create():
    """Creates a new backup with the given tag"""
    config = Config()
    Dialog.info("Creating archive...")
    Restic(config).create(tags=["backup"])


def restore():
    """Deletes the target directory and restores the latest archive"""
    config = Config()

    # Snapshot and delete the existing directory
    if os.path.exists(config.get_directory()):    
        Dialog.info("Creating snapshot archive...")
        Restic(config).create(tags=["snapshot"])

        if not Dialog.truefalse(f"Delete \"{ config.get_directory() }\"?", true="Delete directory", false="Cancel"):
            raise RuntimeError("Action cancelled by user")
        shutil.rmtree(config.get_directory())

    # Restore the archive and move it into the final location
    Dialog.info("Restoring latest archive (this may take some time)...")
    Restic(config).restore(f"{ config.get_directory() }.restic-restore")

    Dialog.info("Moving restored directory into final location...")
    restored = f"{ config.get_directory() }.restic-restore/{ config.get_directory() }"
    shutil.move(restored, config.get_directory())
    shutil.rmtree(f"{ config.get_directory() }.restic-restore")


def check():
    """Checks the repository consistency and integrity"""
    config = Config()
    Dialog.info("Verifying archive...")
    Restic(config).check()


def break_lock():
    """Breaks a stale repository lock"""
    config = Config()
    Dialog.info("Breaking lock...")
    Restic(config).break_lock()


def tmux():
    """Starts a tmux session with the configuration exported as environment"""
    config = Config()
    env = {
        **os.environ,
        **config.env()
    }
    Command(["/usr/bin/env", "tmux"], env=env).display()


if __name__ == "__main__":
    commands = {
        "help": lambda _argv: help(0),
        "list": lambda _argv: list(),
        "backup": lambda _argv: create(),
        "create": lambda _argv: create(),
        "restore": lambda _argv: restore(),
        "check": lambda _argv: check(),
        "verify": lambda _argv: check(),
        "break-lock": lambda _argv: break_lock(),
        "tmux": lambda _argv: tmux()
    }
    if len(sys.argv) > 1 and sys.argv[1] in commands:
        commands[sys.argv[1]](sys.argv[2:])
    else:
        help(exitcode=1) 