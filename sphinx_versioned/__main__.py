import sys
import typer
from typing_extensions import Annotated

from loguru import logger as log

from sphinx_versioned.build import VersionedDocs
from sphinx_versioned.sphinx_ import EventHandlers
from sphinx_versioned.lib import mp_sphinx_compatibility, parse_branch_selection

app = typer.Typer(add_completion=False)


@app.command(help="Create sphinx documentation with a version selector menu.")
def main(
    chdir: Annotated[
        str,
        typer.Option(help="Make this the current working directory before running.")
    ] = None,
    output_dir: Annotated[
        str,
        typer.Option("--output", "-o", help="Output directory.")
    ] = "docs/_build",
    git_root: Annotated[
        str,
        typer.Option(help="Path to directory in the local repo. Default is CWD.", show_default=False)
    ] = None,
    local_conf: Annotated[
        str,
        typer.Option(help="Path to conf.py for sphinx-versions to read config from.")
    ] = "docs/conf.py",
    reset_intersphinx_mapping: Annotated[
        bool,
        typer.Option("--reset-intersphinx", "-rI", help="Reset intersphinx mapping; acts as a patch for issue #17")
    ] = False,
    sphinx_compatibility: Annotated[
        bool,
        typer.Option("--sphinx-compatibility", "-Sc", help="Adds compatibility for older sphinx versions by monkey patching certain functions.")
    ] = False,
    prebuild: Annotated[
        bool,
        typer.Option(help="Pre-builds the documentations; Use `--no-prebuild` to half the runtime.")
    ] = True,
    branches: Annotated[
        str,
        typer.Option("--branch", "-b", help="Build documentation for specific branches and tags.")
    ] = None,
    branch_regex: Annotated[
        str,
        typer.Option(help="Build documentation for specific branches and tags, matched by provided regex")
    ] = None,
    main_branch: Annotated[
        str,
        typer.Option("--main-branch", "-m", help="Main branch to which the top-level `index.html` redirects to. Defaults to `main`.", show_default="main")
    ] = None,
    floating_badge: Annotated[
        bool,
        typer.Option(help="Turns the version selector menu into a floating badge.")
    ] = False,
    quite: Annotated[
        bool,
        typer.Option(help="Silent `sphinx`. Use `--no-quite` to get build output from `sphinx`.")
    ] = True,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Passed directly to sphinx. Specify more than once for more logging in sphinx.")
    ] = False,
    loglevel: Annotated[
        str,
        typer.Option("--log", help="Provide logging level. Example --log debug")
    ] = "info",
    force_branches: Annotated[
        bool,
        typer.Option("--force", help="Force branch selection. Use this option to build detached head/commits. [Default: False]")
    ] = False,
    cache: Annotated[
        str,
        typer.Option(help="Path to directory with previously build versioned docs. The builder will use it, to avoid rebuilding valid versions")
    ] = None
) -> None:
    """
    Typer application for initializing the ``sphinx-versioned`` build.

    Parameters
    ----------
    chdir : :class:`str`
        Make this the current working directory before running. [Default = `None`]
    output_dir : :class:`str`
        Output directory. [Default = 'docs/_build']
    git_root : :class:`str`
        Path to directory in the local repo. Default is CWD.
    local_conf : :class:`str`
        Path to conf.py for sphinx-versions to read config from.
    reset_intersphinx_mapping : :class:`bool`
        Reset intersphinx mapping; acts as a patch for issue #17
    sphinx_compatibility : :class:`bool`
        Adds compatibility for older sphinx versions by monkey patching certain functions.
    prebuild : :class:`bool`
        Pre-builds the documentations; Use `--no-prebuild` to half the runtime. [Default = `True`]
    branches : :class:`str`
        Build docs for specific branches and tags. [Default = `None`]
    main_branch : :class:`str`
        Main branch to which the top-level `index.html` redirects to. [Default = 'main']
    floating_badge : :class:`bool`
        Turns the version selector menu into a floating badge. [Default = `False`]
    quite : :class:`bool`
        Quite output from `sphinx`. Use `--no-quite` to get output from `sphinx`. [Default = `True`]
    verbose : :class:`bool`
        Passed directly to sphinx. Specify more than once for more logging in sphinx. [Default = `False`]
    loglevel : :class:`str`
        Provide logging level. Example `--log` debug, [Default='info']
    force_branches : :class:`str`
        Force branch selection. Use this option to build detached head/commits. [Default = `False`]

    Returns
    -------
    :class:`sphinx_versioned.build.VersionedDocs`
    """
    logger_format = "| <level>{level: <8}</level> | - <level>{message}</level>"

    log.remove()
    log.add(sys.stderr, format=logger_format, level=loglevel.upper())

    select_branches, exclude_branches = parse_branch_selection(branches)

    EventHandlers.RESET_INTERSPHINX_MAPPING = reset_intersphinx_mapping
    EventHandlers.FLYOUT_FLOATING_BADGE = floating_badge

    if reset_intersphinx_mapping:
        log.warning("Forcing --no-prebuild")
        prebuild = False

    if sphinx_compatibility:
        mp_sphinx_compatibility()

    return VersionedDocs(
        {
            "chdir": chdir,
            "output_dir": output_dir,
            "git_root": git_root,
            "local_conf": local_conf,
            "prebuild_branches": prebuild,
            "select_branches": select_branches,
            "exclude_branches": exclude_branches,
            "branch_regex": branch_regex,
            "main_branch": main_branch,
            "quite": quite,
            "verbose": verbose,
            "force_branches": force_branches,
            "cache" : cache
        }
    )


if __name__ == "__main__":
    app()
