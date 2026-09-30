"""Command-line launcher: run the API + bundled web UI as one process.

Installed as the ``camoufox-pm`` console script. Starts the server and opens the
web UI in the default browser. The ``user`` subcommands manage login accounts —
they exist on the CLI, not the API, so the first user can be created without a
chicken-and-egg lockout and creating accounts requires shell access to the host.
"""

import argparse
import asyncio
import getpass
import os
import sys
import threading
import webbrowser
from typing import NoReturn

import uvicorn

from camoufox_pm.config import get_settings
from camoufox_pm.core.database import StorageManager
from camoufox_pm.core.leases import lease_expired


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="camoufox-pm",
        description="Run the Camoufox Profile Manager (API + web UI) on one port.",
    )
    parser.add_argument("--host", default=settings.host, help="Bind address")
    parser.add_argument("--port", type=int, default=settings.port, help="Port")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Open a native desktop window instead of a browser tab (needs the 'desktop' extra)",
    )

    subcommands = parser.add_subparsers(dest="command")
    user_parser = subcommands.add_parser(
        "user",
        help="Manage login accounts (creating the first one turns login on)",
        description=(
            "Manage web UI login accounts. As long as any account exists, the API "
            "requires a login session or the API key; removing the last one turns "
            "login off again."
        ),
    )
    user_commands = user_parser.add_subparsers(dest="user_command", required=True)

    add = user_commands.add_parser("add", help="Create an account (prompts for the password)")
    add.add_argument("username")
    add.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from the first line of stdin instead of prompting",
    )

    passwd = user_commands.add_parser("passwd", help="Change an account's password")
    passwd.add_argument("username")
    passwd.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from the first line of stdin instead of prompting",
    )

    remove = user_commands.add_parser("remove", help="Delete an account and its sessions")
    remove.add_argument("username")

    user_commands.add_parser("list", help="List accounts (never shows password hashes)")

    # Shell-only on purpose, like the user commands above. A force-unlock in the
    # HTTP API would become a button, and a button is the shortest path back to
    # two machines driving one identity — the corruption the lease prevents.
    unlock = subcommands.add_parser(
        "unlock",
        help="Force-release the lease on a profile",
        description=(
            "Clear the lease holding a profile, whatever it says. Needed only when a "
            "machine died in a way its lease cannot notice, or when you have checked "
            "that the holder is really gone: a live lease means another instance may "
            "be driving this profile right now."
        ),
    )
    unlock.add_argument("profile_id")
    unlock.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")

    subcommands.add_parser(
        "leases",
        help="List the profiles currently leased, and by whom",
    )

    # The browser is not bundled with the app, and fetching it means running
    # camoufox's own installer. A frozen build has no `camoufox` command to run
    # from the outside, so it has to carry the installer itself. Shell-only, like
    # the user commands: writing hundreds of megabytes is not a button.
    fetch = subcommands.add_parser(
        "fetch",
        help="Download the Camoufox browser (not bundled; a few hundred MB)",
        description=(
            "Download and install Camoufox. The browser is distributed separately "
            "from this app because of its size, so a fresh install has none and "
            "cannot launch a profile until this has run once. The standalone "
            "desktop build keeps it inside its own folder."
        ),
    )
    fetch.add_argument(
        "--force",
        action="store_true",
        help="Download a fresh copy even if a browser is already installed",
    )
    fetch.add_argument(
        "--prerelease",
        action="store_true",
        help="Allow a prerelease build (newer fingerprints, a much larger download)",
    )

    args = parser.parse_args()

    if args.command == "user":
        asyncio.run(_run_user_command(args))
        return

    if args.command == "unlock":
        asyncio.run(_run_unlock_command(args))
        return

    if args.command == "leases":
        asyncio.run(_run_leases_command())
        return

    if args.command == "fetch":
        _run_fetch_command(args)
        return

    # Make the settings match what we are about to bind, so everything that reads
    # them (the Settings screen, CORS, logs) reports the real address rather than
    # the default the flags just overrode.
    os.environ["CPM_HOST"] = args.host
    os.environ["CPM_PORT"] = str(args.port)
    get_settings.cache_clear()

    if args.desktop:
        from camoufox_pm.desktop import run_desktop

        run_desktop(host=args.host, port=args.port)
        return

    if not args.no_browser:
        url = f"http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}/"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # Import the app object (not an import string) so this works inside a frozen
    # PyInstaller bundle where uvicorn cannot resolve the module by name.
    from camoufox_pm.main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def _fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _read_password(args: argparse.Namespace) -> str:
    """Collect a password without it ever appearing in argv or the environment."""
    from camoufox_pm.core.auth import MIN_PASSWORD_LENGTH

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            _fail("Passwords do not match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        _fail(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


async def _run_unlock_command(args: argparse.Namespace) -> None:
    """Force-release one profile's lease; shell-only (see the parser)."""
    storage = StorageManager(get_settings().db_path)
    await storage.initialize()
    try:
        lease = await storage.get_lease(args.profile_id)
        if lease is None:
            _fail(f"No profile with ID '{args.profile_id}'.")
        holder, expires = lease
        if holder is None:
            print(f"Profile {args.profile_id} is not leased.")
            return
        state = "expired" if lease_expired(expires) else "live"
        print(
            f"Profile {args.profile_id} is leased by {holder}"
            + (f" until {expires} UTC ({state})" if expires else " (no expiry)")
        )
        if not args.yes and input("Force-release this lease? (yes/no): ").strip().lower() not in (
            "yes",
            "y",
        ):
            print("Cancelled; the lease stands.")
            return
        previous = await storage.force_release_lease(args.profile_id)
        print(f"Lease released (was held by {previous}).")
    finally:
        await storage.close()


async def _run_leases_command() -> None:
    """Show who holds what, so `unlock` is a decision and not a guess."""
    storage = StorageManager(get_settings().db_path)
    await storage.initialize()
    try:
        holders = await storage.get_lease_holders()
        if not holders:
            print("No profiles are leased.")
            return
        for entry in holders:
            state = "expired" if entry["expired"] else "live"
            print(
                f"{entry['id']}  {entry['name']}  {entry['locked_by']}  "
                f"expires {entry['lock_expires']} UTC ({state})"
            )
    finally:
        await storage.close()


def _rate_limit_hint(exc: BaseException) -> str:
    """Explain the one failure worth explaining: GitHub's anonymous API quota.

    Sixty calls an hour per address is easy to exhaust on a shared connection,
    and the message the API returns does not say what to do about it.
    """
    if "rate limit" not in str(exc).lower():
        return ""
    return (
        "\nGitHub allows 60 anonymous API calls an hour per address. Setting "
        "GITHUB_TOKEN to a personal access token raises that to 5,000."
    )


def _run_fetch_command(args: argparse.Namespace) -> None:
    """Install the Camoufox browser, which the app launches profiles with."""
    from camoufox.exceptions import CamoufoxNotInstalled
    from camoufox.pkgman import CamoufoxFetcher, installed_verstr, list_available_versions

    if not args.force:
        try:
            print(f"Camoufox browser already installed: v{installed_verstr()}")
            print("Pass --force to download a fresh copy anyway.")
            return
        except CamoufoxNotInstalled:
            pass

    try:
        builds = list_available_versions(include_prerelease=args.prerelease)
    except Exception as exc:  # noqa: BLE001 - a failed lookup deserves a sentence
        _fail(f"Could not list the available Camoufox builds: {exc}{_rate_limit_hint(exc)}")

    if not builds:
        _fail("No Camoufox build is available for this platform.")

    # Newest first, and stable-only unless --prerelease was passed: the
    # prerelease builds are several times larger because they carry fonts.
    target = builds[0]
    size = f"{target.asset_size / 1_000_000:.0f} MB" if target.asset_size else "unknown size"
    print(f"Downloading {target.display} ({size}). This runs once and takes a while.")

    try:
        CamoufoxFetcher(selected_version=target).install(replace=args.force)
    except Exception as exc:  # noqa: BLE001 - the reason, not a traceback
        _fail(f"Installing {target.display} failed: {exc}{_rate_limit_hint(exc)}")

    print(f"Camoufox browser v{installed_verstr()} installed.")


async def _run_user_command(args: argparse.Namespace) -> None:
    # Imported here so plain `camoufox-pm` startup does not pay for them.
    from camoufox_pm.core import auth
    from camoufox_pm.core.database import StorageManager

    storage = StorageManager(get_settings().db_path)
    await storage.initialize()
    try:
        if args.user_command == "add":
            password = _read_password(args)
            try:
                await storage.create_user(
                    auth.new_user_id(), args.username, auth.hash_password(password)
                )
            except ValueError as exc:
                _fail(str(exc))
            print(
                f"User '{args.username}' created. The API and web UI now require "
                "a login session (or the API key, if CPM_API_KEY is set)."
            )
        elif args.user_command == "passwd":
            password = _read_password(args)
            if not await storage.update_user_password(args.username, auth.hash_password(password)):
                _fail(f"No user named '{args.username}'.")
            print(f"Password updated for '{args.username}'.")
        elif args.user_command == "remove":
            if not await storage.delete_user(args.username):
                _fail(f"No user named '{args.username}'.")
            print(f"User '{args.username}' removed, along with any open sessions.")
            if await storage.count_users() == 0:
                print(
                    "No users remain: login is now disabled and the API is back to its API-key/open behaviour."
                )
        elif args.user_command == "list":
            users = await storage.list_users()
            if not users:
                print("No users. Create one with: camoufox-pm user add <name>")
            for user in users:
                print(f"{user['username']}\t(created {user['created_at']})")
    finally:
        await storage.close()


if __name__ == "__main__":
    main()
