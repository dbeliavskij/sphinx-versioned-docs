import os
import fnmatch
import re
import shutil
import pathlib
from sphinx import application
from sphinx.errors import SphinxError
from sphinx.cmd.build import build_main
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from loguru import logger as log

from sphinx_versioned.sphinx_ import EventHandlers
from sphinx_versioned.lib import TempDir, ConfigInject
from sphinx_versioned.versions import GitVersions, BuiltVersions, PseudoBranch
from enum import Enum


class VersionedDocs:
    """Handles main build workflow.

    Chronologically, the :meth:`~sphinx_versioned.__init__` first parses the config
    (input parameters via a :class:`dict`) and then handles various paths, like current
    workding directory, source directory and output directory.
    Further, it selects the branches to pre-build/build then finally generates the
    top-level ``index.html`` file.

    Parameters
    ----------
    config : :class:`dict`
    """

    class CacheState(Enum):
        MISSING = "missing"
        OUTDATED = "outdated"
        VALID = "valid"

    def __init__(self, config: dict, debug: bool = False) -> None:
        self.config = config
        self._parse_config(config)
        self._handle_paths(debug)

        self._versions_to_pre_build = []
        self._versions_to_build = []
        self._failed_build = []

        # Get all versions and make a lookup table
        self._all_branches = self.versions.all_versions
        self._lookup_branch = {x.name: x for x in self._all_branches}

        self._select_exclude_branches()

        # if `--force` is supplied with no `--main-branch`, make the `_active_branch` as the `main_branch`
        if not self.main_branch:
            if self.force_branches:
                self.main_branch = self.versions.active_branch.name
            else:
                self.main_branch = "main"

        if debug:
            return

        self.prebuild()

        # Adds our extension to the sphinx-config
        application.Config = ConfigInject

        self.build()

        # Adds a top-level `index.html` in `output_dir` which redirects to `output_dir`/`main-branch`/index.html
        self._generate_top_level_index()
        self._generate_version_picker()

        print(f"\n\033[92m Successfully built {', '.join([x.name for x in self._built_version])} \033[0m")
        return

    def _parse_config(self, config: dict) -> bool:
        for varname, value in config.items():
            setattr(self, varname, value)

        self._additional_args = ()
        self._additional_args += ("-Q",) if self.quite else ()
        self._additional_args += ("-vv",) if self.verbose else ()
        return True

    def _handle_paths(self, allow_dirty_repos) -> None:
        """Method to handle cwd and path for local config, as well as, configure
        :class:`~sphinx_versioned.versions.GitVersions` and the output directory.
        """
        self.chdir = self.chdir if self.chdir else os.getcwd()
        log.debug(f"Working directory {self.chdir}")

        self.versions = GitVersions(self.git_root, self.output_dir, self.force_branches, allow_dirty_repos=allow_dirty_repos)
        self.output_dir = pathlib.Path(self.output_dir)
        self.local_conf = pathlib.Path(self.local_conf)

        if self.local_conf.name != "conf.py":
            self.local_conf = self.local_conf / "conf.py"

        if not self.local_conf.exists():
            log.error(f"conf.py does not exist at {self.local_conf}")
            raise FileNotFoundError(f"conf.py not found at {self.local_conf.parent}")

        log.success(f"located conf.py")
        return
    
    def _are_different_paths(path1, path2):
        p1 = Path(path1).resolve()
        p2 = Path(path2).resolve()
        return p1 != p2

    def _select_branches(self) -> None:
        if not self.select_branches and not self.branch_regex:
            self._versions_to_pre_build = self._all_branches
            return

        for tag in self.select_branches:
            filtered_tags = fnmatch.filter(self._lookup_branch.keys(), tag)
            if filtered_tags:
                self._versions_to_pre_build.extend([self._lookup_branch.get(x) for x in filtered_tags])
            elif self.force_branches:
                log.warning(f"Forcing build for branch `{tag}`, be careful, it may or may not exist!")
                self._versions_to_pre_build.append(PseudoBranch(self.versions.repo, tag))
            else:
                log.critical(f"Branch not found/selected: `{tag}`, use `--force` to force the build")

        if self.branch_regex:
            regex = re.compile(self.branch_regex)
            regex_tags = [k for k in self._lookup_branch.keys() if regex.match(k)]
            log.debug(f"Matched tags with regex: {regex_tags}")
            if regex_tags:
                self._versions_to_pre_build.extend([self._lookup_branch.get(x) for x in regex_tags])

        return

    def _exclude_branches(self) -> None:
        if not self.exclude_branches:
            return

        _names_versions_to_pre_build = [x.name for x in self._versions_to_pre_build]
        for tag in self.exclude_branches:
            filtered_tags = fnmatch.filter(_names_versions_to_pre_build, tag)
            for x in filtered_tags:
                self._versions_to_pre_build.remove(self._lookup_branch.get(x))

        return

    def _select_exclude_branches(self) -> list:
        log.debug(f"Instructions to select: `{self.select_branches}`")
        log.debug(f"Instructions to exclude: `{self.exclude_branches}`")
        self._versions_to_pre_build = []

        self._select_branches()
        self._exclude_branches()

        log.info(f"selected branches: `{[x.name for x in self._versions_to_pre_build]}`")
        return

    def _generate_top_level_index(self) -> None:
        """Generate a top-level ``index.html`` which redirects to the main-branch version specified
        via ``main_branch``.
        """
        if self.main_branch not in [x.name for x in self._built_version]:
            log.critical(
                f"main branch `{self.main_branch}` not found!! / not building `{self.main_branch}`; "
                "top-level `index.html` will not be generated!"
            )
            return

        log.success(f"main branch: `{self.main_branch}`; generating top-level `index.html`")
        with open(self.output_dir / "index.html", "w") as findex:
            findex.write(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                <meta http-equiv="refresh" content="0; url =
                {self.main_branch.replace("/", "_").replace("\\", "_")}/index.html" />
                </head>
            """
            )
        return
    
    def _generate_version_picker(self):
        log.info("Generating version picker")
        templates_dir = os.path.join(os.path.dirname(__file__), "_templates")
        env = Environment(loader=FileSystemLoader(templates_dir), autoescape=True)
        template = env.get_template("versions_picker.html")
        with open(self.output_dir / "versions_picker.html", "w") as picker_file:
            picker_file.write(template.render(versions=EventHandlers.VERSIONS))

    def _check_cache(self, tag, out_dir_name) -> CacheState:
        if self.cache is None:
            return self.CacheState.MISSING

        cache_dir = os.path.join(self.cache, out_dir_name)
        cache_sha_filename = os.path.join(cache_dir, ".sha")
        index_filename = os.path.join(cache_dir, "index.html")

    
        if not (os.path.exists(index_filename) and os.path.exists(cache_sha_filename)):
            return self.CacheState.MISSING

        with open(cache_sha_filename, "r") as sha_file:
            if sha_file.read() == tag.commit.hexsha:
                return self.CacheState.VALID
            else:
                return self.CacheState.OUTDATED

    def _build(self, tag, _prebuild: bool = False) -> bool:
        """Internal build method which actually carries out the pre-build/build transctions
        inside a temporary directory then copy the asset files to the output directory
        if it's not a pre-build.

        Parameters
        ----------
        tag : :class:`git.Branch` or :class:`git.Tag`
            Branch/tag to build.
        _prebuild : :class:`bool`
            Variable to perform/skip pre-builds for selected/all versions.

        Returns
        -------
        :class:`bool`
        """
        # Setup paths and variables
        tag_dir = tag.name.replace("/", "_")
        output_with_tag = self.output_dir / tag_dir
        cache_with_tag = os.path.join(self.cache, tag_dir) if self.cache else None
        cache_state = self._check_cache(tag, tag_dir)

        if not output_with_tag.exists():
                output_with_tag.mkdir(parents=True, exist_ok=True)

        with TempDir() as temp_dir:
            build_allowed = True
            if (self.update_only is not None) and not fnmatch.fnmatch(tag.name, self.update_only):
                log.info(f"Won't rebuild due to `--update-only {self.update_only}`. Checking cache")
                build_allowed = False

            if cache_state is self.CacheState.VALID:
                log.success(f"Cache is up-to-date for {tag}. Reusing and skipping build")
                if VersionedDocs._are_different_paths(cache_with_tag, output_with_tag):
                    shutil.copytree(cache_with_tag, output_with_tag, False, None, dirs_exist_ok=True)
                return True
            elif cache_state is self.CacheState.OUTDATED:
                log.info(f"Cache is outdated for {tag}. Building")
                copy_destination = temp_dir if build_allowed else output_with_tag
                # Still copy, so that sphinx incremental build could be utilized
                shutil.copytree(cache_with_tag, copy_destination, False, None, dirs_exist_ok=True)
            else:
                log.info("Cache is missing or not enabled.")

            if not build_allowed:
                return False if cache_state is self.CacheState.MISSING else True

            # Checkout tag/branch
            self.versions.checkout(tag)
            EventHandlers.CURRENT_VERSION = tag.name

            log.debug(f"Checking out the tag in temporary directory: {temp_dir}")
            source = str(self.local_conf.parent)
            target = temp_dir
            argv = (source, target)
            argv += self._additional_args
            result = build_main(argv)
            if result != 0:
                raise SphinxError

            if _prebuild:
                log.success(f"pre-build succeeded for {tag} :)")
                return True

            with open(os.path.join(temp_dir, ".sha"), "w") as sha_file:
                sha_file.write(tag.commit.hexsha)

            shutil.copytree(temp_dir, output_with_tag, False, None, dirs_exist_ok=True)
            log.success(f"build succeeded for {tag} ;)")
            return True

    def prebuild(self) -> None:
        """Pre-build workflow.

        Method to pre-build the selected/all branches in a temporary environment. Essentially, it builds
        the various selected/all branches with the vanilla sphinx-build method and pass-on the branches
        which ends up successful in vanilla sphinx-build.

        The method carries out the transaction via the internal build method
        :meth:`~sphinx_versioned.build.VersionedDocs._build`.
        """
        if not self.prebuild_branches:
            log.info("No pre-builing...")
            self._versions_to_build = self._versions_to_pre_build
            return

        log.debug("Pre-building...")

        # get active branch
        self._active_branch = self.versions.active_branch

        try:
            for tag in self._versions_to_pre_build:
                log.info(f"pre-building: {tag}")
                self._build(tag, _prebuild=True)
                self._versions_to_build.append(tag)
        except SphinxError:
            log.critical(f"Pre-build failed for {tag}")
        finally:
            # restore to active branch
            self.versions.checkout(self._active_branch)

        log.success(f"Prebuilding successful for {', '.join([x.name for x in self._versions_to_build])}")
        return

    def build(self) -> None:
        """Build workflow.

        Method to build the branch in a temporary directory with the modified
        :class:`sphinx_versioned.lib.ConfigInject` and injectes the versions flyout menu to the
        footer or the sidebars.

        The method carries out the transaction via the internal build method
        :meth:`~sphinx_versioned.build.VersionedDocs._build`.
        """
        # get active branch
        self._active_branch = self.versions.active_branch

        self._built_version = []

        try:
            for tag in self._versions_to_build:
                log.info(f"Building: {tag}")
                if self._build(tag):
                    self._built_version.append(tag)
        except SphinxError:
            log.error(f"build failed for {tag}")
            exit(-1)
        finally:
            # restore to active branch
            EventHandlers.VERSIONS = BuiltVersions(self._built_version, self.versions.build_directory)
            self.versions.checkout(self._active_branch)
        return

    pass
