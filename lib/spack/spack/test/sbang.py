# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""\
Test that Spack's shebang filtering works correctly.
"""
import os
import stat
import pytest
import tempfile
import shutil
import filecmp

import llnl.util.filesystem as fs

import spack.paths
import spack.store
import spack.hooks.sbang as sbang
from spack.util.executable import which


short_line        = "#!/this/is/short/bin/bash\n"
long_line         = "#!/this/" + ('x' * 200) + "/is/long\n"
lua_line          = "#!/this/" + ('x' * 200) + "/is/lua\n"
lua_in_text       = ("line\n") * 100 + "lua\n" + ("line\n" * 100)
lua_line_patched  = "--!/this/" + ('x' * 200) + "/is/lua\n"
node_line         = "#!/this/" + ('x' * 200) + "/is/node\n"
node_in_text      = ("line\n") * 100 + "lua\n" + ("line\n" * 100)
node_line_patched = "//!/this/" + ('x' * 200) + "/is/node\n"
sbang_line        = '#!/bin/bash %s/bin/sbang\n' % spack.store.layout.root
last_line         = "last!\n"


class ScriptDirectory(object):
    """Directory full of test scripts to run sbang instrumentation on."""
    def __init__(self):
        self.tempdir = tempfile.mkdtemp()

        self.directory = os.path.join(self.tempdir, 'dir')
        fs.mkdirp(self.directory)

        # Script with short shebang
        self.short_shebang = os.path.join(self.tempdir, 'short')
        with open(self.short_shebang, 'w') as f:
            f.write(short_line)
            f.write(last_line)

        # Script with long shebang
        self.long_shebang = os.path.join(self.tempdir, 'long')
        with open(self.long_shebang, 'w') as f:
            f.write(long_line)
            f.write(last_line)

        # Lua script with long shebang
        self.lua_shebang = os.path.join(self.tempdir, 'lua')
        with open(self.lua_shebang, 'w') as f:
            f.write(lua_line)
            f.write(last_line)

        # Lua script with long shebang
        self.lua_textbang = os.path.join(self.tempdir, 'lua_in_text')
        with open(self.lua_textbang, 'w') as f:
            f.write(short_line)
            f.write(lua_in_text)
            f.write(last_line)

        # Node script with long shebang
        self.node_shebang = os.path.join(self.tempdir, 'node')
        with open(self.node_shebang, 'w') as f:
            f.write(node_line)
            f.write(last_line)

        # Node script with long shebang
        self.node_textbang = os.path.join(self.tempdir, 'node_in_text')
        with open(self.node_textbang, 'w') as f:
            f.write(short_line)
            f.write(node_in_text)
            f.write(last_line)

        # Script already using sbang.
        self.has_sbang = os.path.join(self.tempdir, 'shebang')
        with open(self.has_sbang, 'w') as f:
            f.write(sbang_line)
            f.write(long_line)
            f.write(last_line)

        # Fake binary file.
        self.binary = os.path.join(self.tempdir, 'binary')
        tar = which('tar', required=True)
        tar('czf', self.binary, self.has_sbang)

    def destroy(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)


@pytest.fixture
def script_dir():
    sdir = ScriptDirectory()
    yield sdir
    sdir.destroy()


def test_shebang_handling(script_dir):
    assert sbang.shebang_too_long(script_dir.lua_shebang)
    assert sbang.shebang_too_long(script_dir.long_shebang)

    assert not sbang.shebang_too_long(script_dir.short_shebang)
    assert not sbang.shebang_too_long(script_dir.has_sbang)
    assert not sbang.shebang_too_long(script_dir.binary)
    assert not sbang.shebang_too_long(script_dir.directory)

    sbang.filter_shebangs_in_directory(script_dir.tempdir)

    # Make sure this is untouched
    with open(script_dir.short_shebang, 'r') as f:
        assert f.readline() == short_line
        assert f.readline() == last_line

    # Make sure this got patched.
    with open(script_dir.long_shebang, 'r') as f:
        assert f.readline() == sbang_line
        assert f.readline() == long_line
        assert f.readline() == last_line

    # Make sure this got patched.
    with open(script_dir.lua_shebang, 'r') as f:
        assert f.readline() == sbang_line
        assert f.readline() == lua_line_patched
        assert f.readline() == last_line

    # Make sure this got patched.
    with open(script_dir.node_shebang, 'r') as f:
        assert f.readline() == sbang_line
        assert f.readline() == node_line_patched
        assert f.readline() == last_line

    assert filecmp.cmp(script_dir.lua_textbang,
                       os.path.join(script_dir.tempdir, 'lua_in_text'))
    assert filecmp.cmp(script_dir.node_textbang,
                       os.path.join(script_dir.tempdir, 'node_in_text'))

    # Make sure this is untouched
    with open(script_dir.has_sbang, 'r') as f:
        assert f.readline() == sbang_line
        assert f.readline() == long_line
        assert f.readline() == last_line


def test_shebang_handles_non_writable_files(script_dir):
    # make a file non-writable
    st = os.stat(script_dir.long_shebang)
    not_writable_mode = st.st_mode & ~stat.S_IWRITE
    os.chmod(script_dir.long_shebang, not_writable_mode)

    test_shebang_handling(script_dir)

    st = os.stat(script_dir.long_shebang)
    assert oct(not_writable_mode) == oct(st.st_mode)


def check_sbang_installation():
    sbang_path = sbang.sbang_install_path()
    sbang_bin_dir = os.path.dirname(sbang_path)
    assert sbang_path.startswith(spack.store.layout.root)

    assert os.path.exists(sbang_path)
    assert fs.is_exe(sbang_path)

    status = os.stat(sbang_path)
    assert (status.st_mode & 0o777) == 0o755

    status = os.stat(sbang_bin_dir)
    assert (status.st_mode & 0o777) == 0o755


def test_install_sbang(install_mockery):
    sbang_path = sbang.sbang_install_path()
    sbang_bin_dir = os.path.dirname(sbang_path)

    assert sbang_path.startswith(spack.store.layout.root)
    assert not os.path.exists(sbang_bin_dir)

    sbang.install_sbang()
    check_sbang_installation()

    # put an invalid file in for sbang
    fs.mkdirp(sbang_bin_dir)
    with open(sbang_path, "w") as f:
        f.write("foo")

    sbang.install_sbang()
    check_sbang_installation()

    # install again and make sure sbang is still fine
    sbang.install_sbang()
    check_sbang_installation()


def test_sbang_fails_without_argument():
    sbang = which(spack.paths.sbang_script)
    sbang(fail_on_error=False)
    assert sbang.returncode == 1


def test_sbang_with_different_shebangs(tmpdir):
    script = str(tmpdir.join("script"))

    def check_sbang(shebang, returncode, expected=None):
        # write a script out with <shebang> on second line
        with open(script, "w") as f:
            f.write("#!{sbang}\n{shebang}\n".format(
                sbang=spack.paths.sbang_script,
                shebang=shebang
            ))

        # test running it through sbang
        sbang = which(spack.paths.sbang_script)

        # sbang -d prints what *would* be executed
        out = sbang("-d", script, output=str, fail_on_error=False)

        # check error status and output vs. expected
        assert sbang.returncode == returncode

        if expected is not None:
            assert expected == out.strip()

    # perl, with and without /usr/bin/env
    check_sbang("#!/path/to/perl", 0, "/path/to/perl -x %s" % script)
    check_sbang("#!/usr/bin/env perl", 0, "/usr/bin/env perl -x %s" % script)

    # perl -w, with and without /usr/bin/env
    check_sbang("#!/path/to/perl -w", 0, "/path/to/perl -w -x %s" % script)
    check_sbang(
        "#!/usr/bin/env perl -w", 0, "/usr/bin/env perl -w -x %s" % script)

    # ruby, with and without /usr/bin/env
    check_sbang("#!/path/to/ruby", 0, "/path/to/ruby -x %s" % script)
    check_sbang("#!/usr/bin/env ruby", 0, "/usr/bin/env ruby -x %s" % script)

    # python, with and without /usr/bin/env
    check_sbang("#!/path/to/python", 0, "/path/to/python %s" % script)
    check_sbang("#!/usr/bin/env python", 0, "/usr/bin/env python %s" % script)

    # simple shell scripts
    check_sbang("#!/bin/sh", 0, "/bin/sh %s" % script)
    check_sbang("#!/bin/bash", 0, "/bin/bash %s" % script)

    # error case: sbang as infinite loop
    check_sbang("#!/path/to/sbang", 1)
    check_sbang("#!/usr/bin/env sbang", 1)

    # lua
    check_sbang("--!/path/to/lua", 0, "/path/to/lua %s" % script)

    # node
    check_sbang("//!/path/to/node", 0, "/path/to/node %s" % script)
