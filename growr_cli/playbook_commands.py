"""Expose packaged playbooks without changing their public contracts."""

import argparse
from importlib import import_module

PLAYBOOKS = {
    "token-screen": "token_screen",
    "token-holders": "token_holders",
    "wallet-holdings": "wallet_holdings",
    "shared-holdings": "shared_holdings",
    "activity": "activity",
}


def add_playbook_parser(subparsers) -> None:
    """Delegate recipe options to the selected playbook's parser."""

    parser = subparsers.add_parser(
        "playbook",
        help="Run a bounded investigation or screening playbook.",
        description="Run an installed playbook. Options after its name "
        "belong to that playbook; each supports --help and --json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
        "  growr playbook token-screen --help\n"
        "  growr playbook token-holders <MINT> --json\n"
        "  growr playbook shared-holdings holders.json --json",
    )
    parser.help_on_error = True
    parser.add_argument("playbook", choices=PLAYBOOKS)
    parser.add_argument("playbook_args", nargs=argparse.REMAINDER)


def run_playbook(args) -> int:
    """Run an allowlisted module using the same Python environment."""

    name = PLAYBOOKS[args.playbook]
    module = import_module("growr_cli.playbooks.%s" % name)
    options = list(args.playbook_args)
    if args.json and "--json" not in options:
        options.append("--json")
    return module.main(options)


def validate_playbook_flags(parser, arguments) -> None:
    """Reject global controls that the playbook would not honor."""

    position = arguments.index("playbook")
    if any(value != "--json" for value in arguments[:position]):
        parser.error(
            "Only --json may precede playbook; put supported limits "
            "after its name (see growr playbook <name> --help)"
        )
