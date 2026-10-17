import pathlib
import subprocess
import unittest


class CoreInstallerTest(unittest.TestCase):
    def test_existing_protected_config_is_checked_with_privilege(self):
        source = (pathlib.Path(__file__).resolve().parents[1] / 'scripts/install-yerbas-core.sh').read_text()
        function = source[source.index('ensure_core_conf() {'):source.index('\nensure_service() {')]
        # Model a config inaccessible to the invoking user but present for sudo.
        # Any privileged write is a regression: a present config must be kept.
        script = '''set -euo pipefail
SUDO=as_root
CORE_CONF=/protected-existing-config/yerbas.conf
as_root() {
    if [[ "$#" -eq 3 && "$1" == test && "$2" == -f && "$3" == "$CORE_CONF" ]]; then
        return 0
    fi
    echo "Unexpected privileged operation" >&2
    return 99
}
''' + function + '\nensure_core_conf\n'
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('preserving it', result.stdout)
