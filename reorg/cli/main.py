#!/usr/bin/env python
# Copyright 2025 George Kontridze

"""reorg CLI main logic."""

import sys
from collections import defaultdict
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import xdg_base_dirs
import yaml
from praw import Reddit
from rich.console import Console
from rich.table import Table
from typer import Option, Typer

if TYPE_CHECKING:
    from praw.models import Multireddit
    from praw.reddit import Subreddit

CTX_SETTINGS: dict[str, Any] = {"help_option_names": ["-h", "--help"]}
REORG_CFG = xdg_base_dirs.xdg_config_home() / "reorg.yaml"

root = Typer(context_settings=CTX_SETTINGS, no_args_is_help=True)
client = Reddit()
console = Console()


class SubSortKey(StrEnum):
    """Subreddit sort key."""

    url = "url"
    display_name = "display_name"
    title = "title"  # type: ignore[assignment]
    subscribers = "subscribers"


@root.command()
def subs(sort: Annotated[SubSortKey, Option("-s", "--sort")] = SubSortKey.url) -> None:
    """List all subscribed subreddits."""
    table = Table()
    table.add_column("url")
    table.add_column("display_name")
    table.add_column("title")
    table.add_column("subscribers")
    table.add_column("feed")

    multis = client.user.multireddits()
    sub_to_multi: dict[Subreddit, set[Multireddit]] = defaultdict(set)
    for m in multis:
        for s in m.subreddits:
            sub_to_multi[s.url].add(m)

    for sub in sorted(
        client.user.subreddits(limit=None),  # type: ignore[arg-type]
        key=lambda s: getattr(s, sort),
        reverse=sort == SubSortKey.subscribers,
    ):
        s = cast("Subreddit", sub)
        table.add_row(
            s.url,
            s.display_name,
            s.title,
            str(s.subscribers),
            (
                ", ".join(m.name for m in sub_to_multi[sub.url])
                if s.url in sub_to_multi
                else None
            ),
        )

    console.print(table)


multis = Typer(context_settings=CTX_SETTINGS)


class MultiRedditSortKey(StrEnum):
    """multireddit sort key."""

    name = "name"  # type: ignore[assignment]
    sub_count = "sub_count"


@multis.command("list")
def list_multis(
    sort: Annotated[
        MultiRedditSortKey,
        Option("-s", "--sort"),
    ] = MultiRedditSortKey.name,  # type: ignore[arg-type]
) -> None:
    """List all multireddits (custom feeds)."""
    table = Table()
    table.add_column("name")
    table.add_column("sub_count")

    for multi in sorted(
        client.user.multireddits(),
        key=(
            lambda m: getattr(m, sort)
            if sort != MultiRedditSortKey.sub_count
            else len(m.subreddits)
        ),
        reverse=sort == MultiRedditSortKey.sub_count,
    ):
        m = cast("Multireddit", multi)
        table.add_row(m.name, str(len(m.subreddits)))

    console.print(table)


def suburl_to_name(u: str) -> str:
    """
    Given a subreddit url, return its name.

    Args:
        u: subreddit url

    Returns:
        subreddit name

    """
    return u.split("/")[2]


@multis.command()
def genconf(out: Annotated[Path, Option("-o", "--output")] = REORG_CFG) -> None:
    """Generate multisub config."""
    conf: dict[str, list[str]] = {}

    for multi in sorted(client.user.multireddits(), key=lambda m: m.name):
        conf[multi.name] = sorted([suburl_to_name(s.url) for s in multi.subreddits])

    match out.name:
        case "-":
            yaml.dump(conf, sys.stdout)

        case _:
            with out.open("w") as f:
                yaml.dump(conf, f)

            console.print(f"wrote {out.resolve().as_posix()}")


class NoAuthenticatedUserError(RuntimeError):
    """Raised when there is no authenticated user."""

    def __init__(self, *_: object) -> None:
        """Raise with simple message."""
        super().__init__("coult not determine authenticated user")


@multis.command()
def apply(infile: Annotated[Path, Option("-i", "--input")] = REORG_CFG) -> None:
    """
    Apply multisub config.

    Raises:
        NoAuthenticatedUserError: If the authenticated user cannot be determined.

    """
    me = client.user.me()
    if me is None:
        raise NoAuthenticatedUserError

    my_subs = {s.display_name for s in client.user.subreddits()}

    cfg: dict[str, list[str]] = {}

    match infile.name:
        case "-":
            console.print("reading config from stdin")
            cfg = yaml.load(sys.stdin, yaml.SafeLoader)

        case _:
            console.print(f"reading config from {infile}")
            with infile.open() as f:
                cfg = yaml.load(f, yaml.SafeLoader)

    local_multis = set(cfg.keys())
    remote_multis = {
        m.name for m in sorted(client.user.multireddits(), key=lambda m: m.name)
    }

    # Remove what's remote but not in config
    deleted = set()
    for to_delete_multi in remote_multis - local_multis:
        console.print(f"{to_delete_multi} not in config - removing")
        client.multireddit(name=to_delete_multi, redditor=me.name).delete()
        deleted.add(to_delete_multi)

    # Add what's in config but not in remote
    added = set()
    for to_create_multi in local_multis - remote_multis:
        console.print(
            f"{to_create_multi} does not exist yet - creating and adding subs",
        )
        client.multireddit.create(
            display_name=to_create_multi.capitalize(),
            subreddits=cfg[to_create_multi],  # type: ignore[arg-type]
        )
        for newsub in cfg[to_create_multi]:
            if newsub in my_subs:
                continue

            console.print(f"not subbsed to {newsub} - subbing")
            client.subreddit(newsub).subscribe()

        added.add(to_create_multi)

    # Update what's in config and remote
    updated = defaultdict(lambda: {"added": [], "removed": []})
    for to_update_multi in local_multis & remote_multis:
        local_subs = set(cfg[to_update_multi])
        remote_subs = {
            sub.display_name
            for sub in client.multireddit(
                name=to_update_multi,
                redditor=me.name,
            ).subreddits
        }
        if local_subs == remote_subs:
            continue

        console.print(
            f"updating {to_update_multi} with {len(cfg[to_update_multi])} subs",
        )
        client.multireddit(name=to_update_multi, redditor=me.name).update(
            subreddits=cfg[to_update_multi],  # type: ignore[arg-type]
        )

        updated[to_update_multi]["added"] = list(local_subs - remote_subs)
        updated[to_update_multi]["removed"] = list(remote_subs - local_subs)

    console.print(f"removed multireddits: {deleted}")
    console.print(f"added multireddits: {added}")
    console.print(f"updated multireddits: {updated.items()}")


root.add_typer(multis, name="multis", help="Manage multireddits (custom feeds).")


def main() -> None:
    """Execute the reorg CLI."""
    root()


if __name__ == "__main__":
    main()
